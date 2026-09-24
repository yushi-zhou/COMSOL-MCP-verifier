"""Deterministic checks of observed facts, with explicit failure on unknown facts."""
from __future__ import annotations

from typing import Any
import math

from ..schemas.model_observation import CHECK_TOPICS, PreflightCheck


def rows(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _one(items: Any, target: str) -> dict:
    matches = [item for item in rows(items) if item.get("id", item.get("tag")) == target]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one observed node {target!r}, found {len(matches)}.")
    return matches[0]


def _known(node: dict, key: str):
    value = node.get(key)
    if value is None or value == "unknown":
        raise ValueError(f"Required fact {key!r} is unavailable.")
    return value


def dataset_binding(facts: dict, dataset: str, solution: str, study: str, *, nonempty: bool = True) -> dict:
    tree = facts.get("studies") or {}
    node = _one(tree.get("datasets"), dataset)
    seen = set()
    while True:
        if any(key in (node.get("properties") or {}) for key in ("data1", "data2")):
            raise ValueError(f"Dataset {dataset!r} has multiple possible solution sources.")
        if node.get("solution") and node["solution"] not in ("auto", "none"):
            break
        tag = node.get("tag")
        if tag in seen or not node.get("source"):
            raise ValueError(f"Dataset {dataset!r} has no verified solution relationship.")
        seen.add(tag)
        node = _one(tree.get("datasets"), node["source"])
    if node["solution"] != solution:
        raise ValueError(f"Dataset {dataset!r} uses solution {node['solution']!r}, expected {solution!r}.")
    sol = _one(tree.get("solutions"), solution)
    if _known(sol, "study") != study:
        raise ValueError(f"Solution {solution!r} does not belong to study {study!r}.")
    _one(tree.get("studies"), study)
    if nonempty and _known(sol, "empty") is not False:
        raise ValueError(f"Solution {solution!r} is empty or its state is unverified.")
    return sol


def check_topics(checks: list[dict]) -> list[str]:
    ids = [PreflightCheck.model_validate(raw).id for raw in checks]
    if len(set(ids)) != len(ids):
        raise ValueError("Preflight check IDs must be unique across profile and problem.")
    return sorted({topic for raw in checks for topic in CHECK_TOPICS[PreflightCheck.model_validate(raw).kind]})


def run_preflight(facts: dict, checks: list[dict]) -> dict:
    results = []
    for raw in checks:
        try:
            check = PreflightCheck.model_validate(raw)
            kind, target = check.kind, check.target
            if kind == "dataset_binding":
                dataset_binding(facts, target, check.solution, check.study, nonempty=check.require_nonempty)
            else:
                topic = CHECK_TOPICS[kind][0]
                node = _one(facts.get(topic), target)
                if kind in {"physics_active", "excitation", "periodic", "material_selection"}:
                    key = "effective_active" if kind in {"excitation", "periodic"} else "active"
                    if _known(node, key) is not True:
                        raise ValueError(f"{target} is not active.")
                if kind in {"excitation", "periodic"}:
                    for name, expected in check.expected.items():
                        actual = _known(node.get("properties") or {}, name)
                        if actual != expected:
                            raise ValueError(f"{target}.{name}: observed {actual!r}, expected {expected!r}.")
                    for name, expected in check.expected_values.items():
                        actual = _known(node.get("evaluated_properties") or {}, name)
                        if (actual.get("status") != "ok" or (actual.get("unit") or "1") != expected.unit
                                or actual.get("value_imag") != 0):
                            raise ValueError(f"{target}.{name}: required real scalar in {expected.unit!r} is unavailable.")
                        value = actual.get("value_real")
                        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                                or abs(value - expected.value) > expected.atol):
                            raise ValueError(f"{target}.{name}: evaluated {value!r}, expected {expected.value} +/- {expected.atol} {expected.unit}.")
                elif kind == "selection_nonempty":
                    if _known(node, "count") <= 0:
                        raise ValueError(f"Selection {target} is empty.")
                elif kind == "material_selection":
                    selection = _one(facts.get("selections"), check.selection)
                    entities = _known(selection, "entities")
                    bound = _known(node.get("selection") or {}, "entities")
                    if (_known(node, "component") != _known(selection, "component")
                            or _known(selection, "geometry") != _known(node.get("selection") or {}, "geometry")
                            or _known(selection, "dimension") != _known(node.get("selection") or {}, "dimension")
                            or not entities or set(_list(entities)) != set(_list(bound))):
                        raise ValueError(f"Material {target} does not cover expected selection {check.selection}.")
                elif kind == "mesh_present":
                    if _known(node.get("stats") or {}, "numelem") <= 0:
                        raise ValueError(f"Mesh {target} has no elements.")
            results.append({"id": check.id, "kind": kind, "status": "passed"})
        except (ValueError, TypeError, KeyError) as exc:
            results.append({"id": raw.get("id", "unknown"), "kind": raw.get("kind"), "status": "failed", "message": str(exc)})
    failures = [item for item in results if item["status"] == "failed"]
    return {"status": "failed" if failures else ("passed" if results else "not_configured"), "valid": not failures, "checks": results}


def _list(value):
    return value if isinstance(value, list) else [value]
