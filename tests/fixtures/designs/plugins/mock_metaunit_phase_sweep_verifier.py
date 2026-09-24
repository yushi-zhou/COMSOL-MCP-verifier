from __future__ import annotations

from typing import Any


PI = 3.141592653589793


def verify(problem_spec: dict[str, Any], model_profile: dict[str, Any], candidate: dict[str, Any], simulation_output: dict[str, Any]) -> dict[str, Any]:
    data_by_lam = simulation_output.get("data_by_lam", {}) or {}
    required_wavelengths = [str(item) for item in problem_spec.get("independent_variables", {}).get("wavelength_nm", [])]
    objectives = list(problem_spec.get("objectives", []) or [])

    if not data_by_lam:
        return {
            "verifier_id": problem_spec.get("verifier_id"),
            "overall_pass": False,
            "summary_metrics": {},
            "per_condition_results": {},
            "failure_reason": "Missing required data_by_lam output.",
            "limiting_constraint": "missing_required_output",
            "warnings": [],
            "failure_category": "missing_required_output",
            "required_outputs": ["data_by_lam"],
        }

    per_condition_results: dict[str, dict[str, Any]] = {}
    failures: list[tuple[str, str]] = []
    all_wavelength_metrics: dict[str, dict[str, float]] = {}

    for wavelength in required_wavelengths:
        if wavelength not in data_by_lam:
            failures.append(("missing_required_output", f"Missing required wavelength {wavelength}."))

    for wavelength, series in data_by_lam.items():
        param_nm = [float(value) for value in series.get("param_nm", [])]
        transmissions = [float(value) for value in series.get("T", [])]
        phases = [float(value) for value in series.get("phi_rad", [])]
        if len(param_nm) < 1 or len(transmissions) != len(param_nm) or len(phases) != len(param_nm):
            per_condition_results[str(wavelength)] = {
                "pass": False,
                "failure_reason": "Malformed per-wavelength series.",
                "failure_category": "malformed_output",
            }
            failures.append(("malformed_output", f"Malformed per-wavelength series for wavelength {wavelength}."))
            continue

        phase_coverage = _phase_coverage(phases)
        mean_transmission = sum(transmissions) / len(transmissions)
        max_abs_dT_dl = _max_abs_gradient(param_nm, transmissions)

        objective_results: dict[str, bool] = {}
        objective_categories: list[str] = []
        for objective in objectives:
            metric_name = str(objective.get("metric", ""))
            direction = str(objective.get("direction", "")).lower()
            target = objective.get("target")
            metric_value = {
                "phase_coverage": phase_coverage,
                "mean_transmission": mean_transmission,
                "max_abs_dT_dl": max_abs_dT_dl,
            }.get(metric_name)

            if metric_value is None or target is None:
                objective_results[metric_name or "unknown"] = False
                objective_categories.append("malformed_output")
                continue

            if direction == "maximize":
                passed = metric_value >= float(target)
            elif direction == "minimize":
                passed = metric_value <= float(target)
            else:
                passed = False
                objective_categories.append("malformed_output")

            objective_results[metric_name] = passed
            if not passed:
                if metric_name == "phase_coverage":
                    objective_categories.append("phase_limited")
                elif metric_name == "mean_transmission":
                    objective_categories.append("transmission_limited")
                elif metric_name == "max_abs_dT_dl":
                    objective_categories.append("fano_limited")
                else:
                    objective_categories.append("mixed")

        per_condition_results[str(wavelength)] = {
            "pass": len(objective_categories) == 0,
            "phase_coverage": phase_coverage,
            "mean_transmission": mean_transmission,
            "max_abs_dT_dl": max_abs_dT_dl,
            "objectives": objective_results,
        }
        all_wavelength_metrics[str(wavelength)] = {
            "phase_coverage": phase_coverage,
            "mean_transmission": mean_transmission,
            "max_abs_dT_dl": max_abs_dT_dl,
        }
        if objective_categories:
            failures.extend((category, f"Wavelength {wavelength} failed objective check(s).") for category in objective_categories)

    summary_metrics = {
        "worst_phase_coverage": min((entry["phase_coverage"] for entry in all_wavelength_metrics.values()), default=0.0),
        "mean_transmission": sum(entry["mean_transmission"] for entry in all_wavelength_metrics.values()) / max(1, len(all_wavelength_metrics)),
        "max_abs_dT_dl": max((entry["max_abs_dT_dl"] for entry in all_wavelength_metrics.values()), default=0.0),
    }

    overall_pass = bool(all_wavelength_metrics) and not failures and all(entry.get("pass") for entry in per_condition_results.values())
    failure_category = _reduce_failure_categories([category for category, _ in failures])
    return {
        "verifier_id": problem_spec.get("verifier_id"),
        "overall_pass": overall_pass,
        "summary_metrics": summary_metrics,
        "per_condition_results": per_condition_results,
        "failure_reason": "" if overall_pass else "; ".join(message for _, message in failures),
        "limiting_constraint": None if overall_pass else failure_category,
        "warnings": [],
        "failure_category": None if overall_pass else failure_category,
        "required_outputs": ["data_by_lam"],
    }


def _phase_coverage(values: list[float]) -> float:
    if not values:
        return 0.0
    unwrapped = [values[0]]
    for value in values[1:]:
        previous = unwrapped[-1]
        candidate = value
        while candidate - previous > PI:
            candidate -= 2 * PI
        while previous - candidate > PI:
            candidate += 2 * PI
        unwrapped.append(candidate)
    return max(unwrapped) - min(unwrapped)


def _max_abs_gradient(param_nm: list[float], transmissions: list[float]) -> float:
    if len(param_nm) < 2:
        return 0.0
    gradients = []
    for left_index in range(len(param_nm) - 1):
        delta_param = param_nm[left_index + 1] - param_nm[left_index]
        if delta_param == 0:
            continue
        delta_t = transmissions[left_index + 1] - transmissions[left_index]
        gradients.append(abs(delta_t / delta_param))
    return max(gradients) if gradients else 0.0


def _reduce_failure_categories(categories: list[str]) -> str:
    unique = [category for category in dict.fromkeys(categories) if category]
    if not unique:
        return "unknown_failure"
    if len(unique) == 1:
        return unique[0]
    if "missing_required_output" in unique:
        return "missing_required_output"
    if "malformed_output" in unique:
        return "malformed_output"
    return "mixed"
