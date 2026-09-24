"""Selective observation of existing artifacts through the fixed LiveLink adapter."""
from __future__ import annotations

import json

from ..backends.base import BackendExecutionError
from ..backends.matlab_livelink_backend import MatlabLiveLinkBackend
from ..schemas.model_observation import selected_measurements, validate_topics
from ..utils.paths import configured_run_root
from ..utils.provenance import capture_provenance, compact_provenance, file_sha256, require_provenance


def compact(value, *, depth: int = 0):
    """Bound every collection, including plugin-owned dictionaries and arrays."""
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "… [see artifact]"
    if depth > 7 and isinstance(value, (list, dict)):
        return {"detail": "see artifact"}
    if isinstance(value, list):
        result = [compact(item, depth=depth + 1) for item in value[:12]]
        if len(value) > 12:
            result.append({"omitted": len(value) - 12, "total": len(value)})
        return result
    if isinstance(value, dict):
        pairs = list(value.items())
        result = {key: compact(item, depth=depth + 1) for key, item in pairs[:24]}
        if len(pairs) > 24:
            result["_omitted_keys"] = len(pairs) - 24
        return result
    return value


def inspect_model_payload(request: dict, profile: dict, problem: dict, packages, *, backend=None) -> dict:
    if (profile.get("backend") or {}).get("type") != "matlab_livelink":
        raise BackendExecutionError("Actual model introspection requires MATLAB LiveLink.", failure_category="inspection_unsupported")
    provenance = capture_provenance(profile, problem, packages)
    require_provenance(request.get("provenance"), provenance)
    source = request.get("source")
    if source and file_sha256(source["path"]) != source["sha256"]:
        raise BackendExecutionError("Saved solved artifact changed since its producing run.", failure_category="stale_provenance")
    topics = validate_topics(request.get("topics"))
    measurements = request.get("measurement_ids") or []
    definitions = selected_measurements(profile, measurements)
    backend = backend or MatlabLiveLinkBackend()
    output = backend.inspect(
        model_profile=profile, problem_spec=problem, run_id=request["job_id"], topics=topics,
        measurement_ids=measurements, source_path=source["path"] if source else None,
    )
    require_provenance(provenance, capture_provenance(profile, problem, packages))
    if source and file_sha256(source["path"]) != source["sha256"]:
        raise BackendExecutionError("Saved solved artifact changed during inspection.", failure_category="stale_provenance")
    recomputed = set(source.get("recomputed_solutions") or []) if source else set()
    verified = bool(definitions) and all(item["solution"] in recomputed for item in definitions)
    freshness = "verified_measurement_solutions" if verified else "unverified_saved_solution"
    facts = output["model_facts"]
    result = {
        "status": "inspected" if output["preflight"]["valid"] else "preflight_failed",
        "overall_pass": None,
        "provenance": provenance,
        "source": source or provenance["model"],
        "solution_freshness": freshness,
        "artifact_receipt_verified": bool(source),
        "recomputed_solutions": sorted(recomputed),
        "facts": {key: facts[key] for key in ("schema_version", *topics, "issues") if key in facts},
        "preflight": output["preflight"],
        "measurements": output["measurements"],
        "measurement_definitions": selected_measurements(profile, measurements) if measurements else profile.get("measurements", []),
        "facts_path": output["facts_path"],
        "warnings": [] if verified else ["Only solutions listed in recomputed_solutions have an execution receipt. Other saved solutions may be stale relative to current parameters/geometry."],
        "errors": [],
    }
    folder = configured_run_root(profile) / request["job_id"]
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return result


def compact_inspection(result: dict) -> dict:
    facts = dict(result.get("facts") or {})
    excitation = facts.get("excitation")
    if isinstance(excitation, list):
        # Surface driven ports before disabled features and passive orders.
        # This presentation order never changes the full evidence or preflight.
        facts["excitation"] = sorted(excitation, key=lambda item: (
            item.get("effective_active") is not True,
            (item.get("properties") or {}).get("PortExcitation") != "on",
        ))
    return {
        **{name: compact(result[name]) for name in ("measurements", "measurement_definitions", "preflight", "solution_freshness", "artifact_receipt_verified", "recomputed_solutions", "facts_path", "source") if name in result},
        "facts": compact(facts),
        "fact_counts": {key: len(value) for key, value in facts.items() if isinstance(value, list)},
        "provenance": compact_provenance(result.get("provenance") or {}),
    }
