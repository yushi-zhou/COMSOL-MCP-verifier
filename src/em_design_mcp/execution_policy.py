from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


DEFAULT_BACKEND_TIMEOUT_SECONDS = 3600

POLICY_KEYS = {
    "allow_real_backend",
    "max_batch_candidates",
    "max_real_evaluations_per_request",
    "backend_timeout_seconds",
    "max_sweep_points",
    "require_validation_before_evaluate",
}


def resolve_execution_policy(model_profile: dict[str, Any], problem_spec: dict[str, Any]) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "allow_real_backend": True,
        "max_batch_candidates": None,
        "max_real_evaluations_per_request": None,
        "backend_timeout_seconds": DEFAULT_BACKEND_TIMEOUT_SECONDS,
        "max_sweep_points": None,
        "require_validation_before_evaluate": True,
    }
    for source in (model_profile.get("execution_policy"), problem_spec.get("execution_policy")):
        if not isinstance(source, dict):
            continue
        for key in POLICY_KEYS:
            if key in source and source[key] is not None:
                policy[key] = deepcopy(source[key])

    policy["allow_real_backend"] = bool(policy["allow_real_backend"])
    policy["require_validation_before_evaluate"] = bool(policy["require_validation_before_evaluate"])
    policy["backend_timeout_seconds"] = _positive_int_or_default(
        policy.get("backend_timeout_seconds"),
        DEFAULT_BACKEND_TIMEOUT_SECONDS,
    )
    policy["max_batch_candidates"] = _positive_int_or_none(policy.get("max_batch_candidates"))
    policy["max_real_evaluations_per_request"] = _positive_int_or_none(
        policy.get("max_real_evaluations_per_request")
    )
    policy["max_sweep_points"] = _positive_int_or_none(policy.get("max_sweep_points"))
    return policy


def estimate_candidate_cost(
    model_profile: dict[str, Any],
    problem_spec: dict[str, Any],
    candidate: dict[str, Any],
    *,
    backend: str = "matlab_livelink",
) -> dict[str, Any]:
    policy = resolve_execution_policy(model_profile, problem_spec)
    warnings: list[str] = []
    errors: list[str] = []

    backend_name = str(backend).strip()
    if backend_name == "matlab_livelink" and not policy["allow_real_backend"]:
        errors.append("Execution policy does not allow backend='matlab_livelink'.")

    sweep_result = _estimate_sweeps(model_profile, problem_spec, candidate)
    warnings.extend(sweep_result["warnings"])
    errors.extend(sweep_result["errors"])

    max_sweep_points = policy.get("max_sweep_points")
    estimated_sweep_points = sweep_result["estimated_sweep_points"]
    if max_sweep_points is not None and estimated_sweep_points is not None and estimated_sweep_points > max_sweep_points:
        errors.append(
            "Estimated sweep cost "
            f"{estimated_sweep_points} exceeds execution_policy.max_sweep_points={max_sweep_points}."
        )

    return {
        "valid": len(errors) == 0,
        "estimated_sweep_points": estimated_sweep_points,
        "estimated_conditions": sweep_result["estimated_conditions"],
        "estimated_geometry_points": sweep_result["estimated_geometry_points"],
        "warnings": warnings,
        "errors": errors,
        "policy_applied": policy,
    }


def _estimate_sweeps(
    model_profile: dict[str, Any],
    problem_spec: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    sweeps = (model_profile.get("model_bindings") or {}).get("sweeps") or []
    if isinstance(sweeps, dict):
        sweeps = [sweeps]
    if not isinstance(sweeps, list):
        return {
            "estimated_sweep_points": None,
            "estimated_conditions": None,
            "estimated_geometry_points": None,
            "warnings": [],
            "errors": ["model_bindings.sweeps must be a list or object when present."],
        }

    warnings: list[str] = []
    errors: list[str] = []
    geometry_points = 1
    range_sweep_count = 0
    condition_points = 1
    values_sweep_count = 0

    for sweep in sweeps:
        if not isinstance(sweep, dict):
            warnings.append("Ignoring non-object sweep binding while estimating cost.")
            continue
        kind = str(sweep.get("kind") or "").strip()
        if kind == "range":
            range_sweep_count += 1
            points = _estimate_range_points(sweep, candidate, errors)
            if points is not None:
                geometry_points *= points
        elif kind == "values":
            values_sweep_count += 1
            points = _estimate_values_points(sweep, model_profile, problem_spec, candidate, warnings, errors)
            if points is not None:
                condition_points *= points
        elif kind:
            warnings.append(f"Cost estimator does not know how to estimate sweep kind {kind!r}.")

    if range_sweep_count == 0:
        sample_points = _estimate_output_sample_points(model_profile, candidate, warnings, errors)
        if values_sweep_count == 0 and sample_points is not None:
            condition_points = sample_points
        warnings.append("No range sweep bindings were found; estimated geometry points are unknown.")
        estimated_geometry_points = 0
        estimated_sweep_points = condition_points if values_sweep_count or sample_points is not None else 0
    else:
        estimated_geometry_points = geometry_points
        estimated_sweep_points = geometry_points * condition_points

    return {
        "estimated_sweep_points": estimated_sweep_points,
        "estimated_conditions": condition_points,
        "estimated_geometry_points": estimated_geometry_points,
        "warnings": warnings,
        "errors": errors,
    }


def _estimate_range_points(sweep: dict[str, Any], candidate: dict[str, Any], errors: list[str]) -> int | None:
    start_field = str(sweep.get("start_field") or "").strip()
    stop_field = str(sweep.get("stop_field") or "").strip()
    if not start_field or not stop_field:
        errors.append("Range sweep must declare start_field and stop_field for cost estimation.")
        return None
    if start_field not in candidate:
        errors.append(f"Candidate is missing range sweep start_field {start_field!r}.")
        return None
    if stop_field not in candidate:
        errors.append(f"Candidate is missing range sweep stop_field {stop_field!r}.")
        return None

    start = _coerce_number(candidate[start_field], f"candidate.{start_field}", errors)
    stop = _coerce_number(candidate[stop_field], f"candidate.{stop_field}", errors)
    step = _coerce_number(sweep.get("step"), "range sweep step", errors)
    if start is None or stop is None or step is None:
        return None
    if step <= 0:
        errors.append("Range sweep step must be positive.")
        return None
    if stop < start:
        errors.append(f"Range sweep stop_field {stop_field!r} must be greater than or equal to start_field {start_field!r}.")
        return None

    return int(math.floor((stop - start) / step + 1e-12)) + 1


def _estimate_values_points(
    sweep: dict[str, Any],
    model_profile: dict[str, Any],
    problem_spec: dict[str, Any],
    candidate: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> int | None:
    if "values" in sweep:
        return _count_values(sweep.get("values"))

    values_from = str(sweep.get("values_from") or "").strip()
    if not values_from:
        warnings.append("Values sweep has neither values nor values_from; assuming one condition.")
        return 1

    resolved = _resolve_dotted_path(
        values_from,
        {
            "candidate": candidate,
            "problem_spec": problem_spec,
            "model_profile": model_profile,
        },
    )
    if resolved is _MISSING:
        errors.append(f"Values sweep values_from path could not be resolved: {values_from!r}.")
        return None
    return _count_values(resolved)


def _estimate_output_sample_points(
    model_profile: dict[str, Any],
    candidate: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> int | None:
    outputs = (model_profile.get("model_bindings") or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        return None
    sample_count_field = str(outputs.get("sample_count_field") or "").strip()
    if not sample_count_field:
        return None
    if sample_count_field not in candidate:
        errors.append(f"Candidate is missing output sample_count_field {sample_count_field!r}.")
        return None
    sample_count = _coerce_number(candidate[sample_count_field], f"candidate.{sample_count_field}", errors)
    if sample_count is None:
        return None
    rounded = int(sample_count)
    if rounded <= 0 or rounded != sample_count:
        errors.append(f"Output sample_count_field {sample_count_field!r} must be a positive integer.")
        return None
    warnings.append(f"Estimated conditions from output sample_count_field {sample_count_field!r}.")
    return rounded


def _count_values(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return 1


def _resolve_dotted_path(path: str, roots: dict[str, Any]) -> Any:
    parts = path.split(".")
    if not parts or parts[0] not in roots:
        return _MISSING
    value: Any = roots[parts[0]]
    for part in parts[1:]:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return _MISSING
    return value


def _coerce_number(value: Any, label: str, errors: list[str]) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be numeric for cost estimation.")
        return None


def _positive_int_or_default(value: Any, default: int) -> int:
    parsed = _positive_int_or_none(value)
    return parsed if parsed is not None else default


def _positive_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class _Missing:
    pass


_MISSING = _Missing()
