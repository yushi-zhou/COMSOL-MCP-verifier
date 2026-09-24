from __future__ import annotations

from typing import Any


def verify(problem_spec: dict[str, Any], model_profile: dict[str, Any], candidate: dict[str, Any], simulation_output: dict[str, Any]) -> dict[str, Any]:
    metrics = simulation_output.get("summary_metrics", {}) or {}
    warnings: list[str] = []
    errors: list[str] = []

    if not metrics:
        errors.append("Missing required summary_metrics output.")

    score = metrics.get("score")
    mean_transmission = metrics.get("mean_transmission")
    if score is not None and score < 0:
        errors.append("score must be non-negative.")
    if mean_transmission is not None and mean_transmission < 0:
        errors.append("mean_transmission must be non-negative.")

    overall_pass = len(errors) == 0
    return {
        "verifier_id": problem_spec.get("verifier_id"),
        "overall_pass": overall_pass,
        "summary_metrics": metrics,
        "per_condition_results": {},
        "failure_reason": " ; ".join(errors),
        "limiting_constraint": None,
        "warnings": warnings,
        "failure_category": "unknown_failure" if errors else None,
        "required_outputs": ["summary_metrics"],
    }
