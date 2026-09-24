from __future__ import annotations

import hashlib
import json
from typing import Any

from ..validation.schema_validation import deep_merge_schema


CONTRACT_HASH_ALGORITHM = "sha256"
DEFAULT_VERIFIER_VERSION = "0.1"


def build_contract_metadata(
    model_profile: dict[str, Any],
    problem_spec: dict[str, Any],
    *,
    verifier_id: str | None = None,
    verifier_version: str | None = None,
) -> dict[str, Any]:
    base_schema = model_profile.get("design_schema")
    if not isinstance(base_schema, dict):
        base_schema = {"type": "object", "properties": {}, "required": []}
    effective_schema = deep_merge_schema(base_schema, problem_spec.get("candidate_schema_overrides"))
    thresholds = contract_thresholds(problem_spec)
    payload = {
        "model_profile_id": model_profile.get("model_profile_id"),
        "model_profile_version": model_profile.get("version"),
        "problem_id": problem_spec.get("problem_id"),
        "problem_version": problem_spec.get("version"),
        "verifier_id": verifier_id or problem_spec.get("verifier_id"),
        "verifier_version": verifier_version or DEFAULT_VERIFIER_VERSION,
        "effective_candidate_schema": effective_schema,
        "thresholds": thresholds,
        "expected_outputs": list(problem_spec.get("expected_outputs") or []),
        "profile_contract": _profile_contract_payload(model_profile),
        "problem_contract": _problem_contract_payload(problem_spec),
    }
    return {
        "model_profile_id": payload["model_profile_id"],
        "model_profile_version": payload["model_profile_version"],
        "problem_id": payload["problem_id"],
        "problem_version": payload["problem_version"],
        "verifier_id": payload["verifier_id"],
        "verifier_version": payload["verifier_version"],
        "contract_hash": stable_contract_hash(payload),
        "contract_hash_algorithm": CONTRACT_HASH_ALGORITHM,
    }


def contract_thresholds(problem_spec: dict[str, Any]) -> dict[str, Any]:
    configured_thresholds = problem_spec.get("thresholds")
    thresholds: dict[str, Any] = {}
    if isinstance(configured_thresholds, dict):
        thresholds.update(configured_thresholds)

    objective_targets: dict[str, Any] = {}
    for objective in problem_spec.get("objectives") or []:
        if not isinstance(objective, dict):
            continue
        metric = str(objective.get("metric") or "").strip()
        if metric and "target" in objective:
            objective_targets[metric] = objective["target"]
    if thresholds and objective_targets:
        thresholds["objective_targets"] = objective_targets
    elif objective_targets:
        thresholds.update(objective_targets)
    return thresholds


def stable_contract_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _profile_contract_payload(model_profile: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in model_profile.items() if not key.startswith("_")}


def _problem_contract_payload(problem_spec: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in problem_spec.items() if not key.startswith("_")}
