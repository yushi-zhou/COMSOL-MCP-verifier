from __future__ import annotations

import difflib
import math
from typing import Any


DEFAULT_BACKEND_TIMEOUT_SECONDS = 3600

BOOLEAN_POLICY_KEYS = {"allow_real_backend", "require_validation_before_evaluate"}
INTEGER_POLICY_KEYS = {
    "max_batch_candidates",
    "max_real_evaluations_per_request",
    "backend_timeout_seconds",
    "max_sweep_points",
}
POLICY_KEYS = BOOLEAN_POLICY_KEYS | INTEGER_POLICY_KEYS
SUPPORTED_SWEEP_KINDS = ("range", "values")


def parse_execution_policy(model_profile: dict[str, Any], problem_spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Merge profile and problem policies (problem wins) and report invalid declarations.

    Invalid values never fall back to permissive defaults: they are returned as
    errors so callers can refuse to run. Real solver runs require an explicit
    ``allow_real_backend: true``.
    """
    policy: dict[str, Any] = {
        "allow_real_backend": False,
        "max_batch_candidates": None,
        "max_real_evaluations_per_request": None,
        "backend_timeout_seconds": DEFAULT_BACKEND_TIMEOUT_SECONDS,
        "max_sweep_points": None,
        "require_validation_before_evaluate": True,
    }
    errors: list[str] = []
    for label, source in (("model profile", model_profile.get("execution_policy")), ("problem", problem_spec.get("execution_policy"))):
        if source is None:
            continue
        if not isinstance(source, dict):
            errors.append(f"The {label} execution_policy must be an object.")
            continue
        for key, value in source.items():
            if key not in POLICY_KEYS:
                errors.append(f"Unknown {label} execution_policy key {key!r}{_did_you_mean(key, POLICY_KEYS)}.")
                continue
            if value is None:
                continue
            if key in BOOLEAN_POLICY_KEYS:
                if not isinstance(value, bool):
                    errors.append(f"The {label} execution_policy.{key} must be true or false, not {value!r}.")
                    continue
                policy[key] = value
            else:
                parsed = _strict_positive_int(value)
                if parsed is None:
                    errors.append(f"The {label} execution_policy.{key} must be a positive integer, not {value!r}.")
                    continue
                policy[key] = parsed
    return policy, errors


def resolve_execution_policy(model_profile: dict[str, Any], problem_spec: dict[str, Any]) -> dict[str, Any]:
    policy, errors = parse_execution_policy(model_profile, problem_spec)
    if errors:
        raise ValueError("Invalid execution_policy: " + " ".join(errors))
    return policy


def estimate_candidate_cost(
    model_profile: dict[str, Any],
    problem_spec: dict[str, Any],
    candidate: dict[str, Any],
    *,
    backend: str = "matlab_livelink",
) -> dict[str, Any]:
    policy, errors = parse_execution_policy(model_profile, problem_spec)
    warnings: list[str] = []

    backend_name = str(backend).strip()
    real_backend = backend_name == "matlab_livelink"
    if real_backend and not policy["allow_real_backend"]:
        message = "Execution policy does not allow backend='matlab_livelink'."
        if not _declares(model_profile, problem_spec, "allow_real_backend"):
            message += " Real solver runs need an explicit execution_policy.allow_real_backend: true in the profile or problem."
        errors.append(message)

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
    if real_backend and max_sweep_points is None and sweep_result["sweep_count"]:
        warnings.append("No execution_policy.max_sweep_points is declared; declared sweep cost is not bounded.")

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
    if isinstance(sweeps, dict) and "kind" not in sweeps and sweeps and all(isinstance(item, dict) for item in sweeps.values()):
        kinds = sorted({str(item.get("kind")) for item in sweeps.values()})
        return _sweep_error(
            f"model_bindings.sweeps must be a list of sweep objects; found named entries {sorted(sweeps)} "
            f"(kind {', '.join(kinds)}), which the LiveLink adapter cannot apply."
        )
    if isinstance(sweeps, dict):
        sweeps = [sweeps]
    if not isinstance(sweeps, list):
        return _sweep_error("model_bindings.sweeps must be a list or object when present.")

    warnings: list[str] = []
    errors: list[str] = []
    geometry_points = 1
    range_sweep_count = 0
    condition_points = 1
    values_sweep_count = 0

    for sweep in sweeps:
        if not isinstance(sweep, dict):
            errors.append("Every model_bindings.sweeps entry must be an object; sweep cost cannot be estimated.")
            continue
        kind = str(sweep.get("kind") or "").strip()
        if kind == "range":
            range_sweep_count += 1
            points = _estimate_range_points(sweep, candidate, errors)
            if points is not None:
                geometry_points *= points
        elif kind == "values":
            values_sweep_count += 1
            points = _estimate_values_points(sweep, model_profile, problem_spec, candidate, errors)
            if points is not None:
                condition_points *= points
        else:
            # The fixed LiveLink adapter rejects anything else at run time; fail
            # before launching MATLAB instead of silently skipping the cost.
            errors.append(
                f"Unsupported sweep binding kind {kind or None!r}; the LiveLink adapter applies only "
                f"{', '.join(SUPPORTED_SWEEP_KINDS)} sweeps (entries need kind, study_tag and feature_tag)."
            )

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
        "sweep_count": range_sweep_count + values_sweep_count,
        "warnings": warnings,
        "errors": errors,
    }


def _sweep_error(message: str) -> dict[str, Any]:
    return {
        "estimated_sweep_points": None,
        "estimated_conditions": None,
        "estimated_geometry_points": None,
        "sweep_count": 0,
        "warnings": [],
        "errors": [message],
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

    # MATLAB formats these with double(); a string would become character codes.
    start = _finite_number(candidate[start_field], f"candidate.{start_field}", errors)
    stop = _finite_number(candidate[stop_field], f"candidate.{stop_field}", errors)
    step = _finite_number(sweep.get("step"), "range sweep step", errors)
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
    errors: list[str],
) -> int | None:
    if "values" in sweep:
        return _count_sweep_values(sweep.get("values"), "values sweep 'values'", errors, from_candidate=False)

    values_from = str(sweep.get("values_from") or "").strip()
    if not values_from:
        errors.append("Values sweep declares neither values nor values_from; sweep cost cannot be estimated.")
        return None

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
    return _count_sweep_values(resolved, values_from, errors, from_candidate=values_from.split(".", 1)[0] == "candidate")


def _count_sweep_values(value: Any, label: str, errors: list[str], *, from_candidate: bool) -> int | None:
    """Count values exactly as the LiveLink adapter expands them.

    MATLAB flattens nested arrays into one list and forwards non-numeric text to
    COMSOL as an expression (for example ``range(...)``), whose size cannot be
    estimated. Nested arrays therefore count every leaf, and expressions fail.
    """
    leaves: list[Any] = []
    _flatten(value, leaves)
    count = 0
    for leaf in leaves:
        if isinstance(leaf, bool):
            if from_candidate:
                errors.append(f"Sweep values from {label} must be numbers, not booleans.")
                return None
            count += 1
        elif isinstance(leaf, (int, float)):
            if not math.isfinite(float(leaf)):
                errors.append(f"Sweep values from {label} must be finite.")
                return None
            count += 1
        elif isinstance(leaf, str) and not from_candidate and _is_numeric_text(leaf):
            count += 1
        else:
            errors.append(
                f"Sweep values from {label} must be numbers; {leaf!r} would be passed to COMSOL as an "
                "expression whose sweep size cannot be bounded."
            )
            return None
    if count == 0:
        errors.append(f"Values sweep {label} resolved no values.")
        return None
    return count


def _flatten(value: Any, leaves: list[Any]) -> None:
    if isinstance(value, (list, tuple)):
        for item in value:
            _flatten(item, leaves)
    elif value is not None:
        leaves.append(value)


def _is_numeric_text(text: str) -> bool:
    try:
        return math.isfinite(float(text.strip()))
    except ValueError:
        return False


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
    sample_count = _finite_number(candidate[sample_count_field], f"candidate.{sample_count_field}", errors)
    if sample_count is None:
        return None
    rounded = int(sample_count)
    if rounded <= 0 or rounded != sample_count:
        errors.append(f"Output sample_count_field {sample_count_field!r} must be a positive integer.")
        return None
    warnings.append(f"Estimated conditions from output sample_count_field {sample_count_field!r}.")
    return rounded


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


def _finite_number(value: Any, label: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        errors.append(f"{label} must be a finite number for cost estimation.")
        return None
    return float(value)


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer() and value > 0:
        return int(value)
    return None


def _declares(model_profile: dict[str, Any], problem_spec: dict[str, Any], key: str) -> bool:
    return any(
        isinstance(source, dict) and source.get(key) is not None
        for source in (model_profile.get("execution_policy"), problem_spec.get("execution_policy"))
    )


def _did_you_mean(key: str, choices: set[str]) -> str:
    match = difflib.get_close_matches(str(key), sorted(choices), n=1, cutoff=0.75)
    return f" (did you mean {match[0]!r}?)" if match else ""


class _Missing:
    pass


_MISSING = _Missing()
