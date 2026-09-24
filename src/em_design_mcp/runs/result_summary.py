from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESULT_SUMMARY_FILENAME = "result_summary.json"


def write_result_summary(
    *,
    run_dir: str | Path,
    run_id: str,
    backend: str,
    model_profile_id: str | None,
    problem_id: str | None,
    candidate: dict[str, Any],
    status: str,
    simulation_output: dict[str, Any],
    overall_pass: bool | None = None,
    failure_category: str | None = None,
    verifier_id: str | None = None,
    verifier_result: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    contract_metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> Path:
    path = Path(run_dir) / RESULT_SUMMARY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_result_summary(
        run_id=run_id,
        backend=backend,
        model_profile_id=model_profile_id,
        problem_id=problem_id,
        candidate=candidate,
        status=status,
        simulation_output=simulation_output,
        overall_pass=overall_pass,
        failure_category=failure_category,
        verifier_id=verifier_id,
        verifier_result=verifier_result,
        warnings=warnings,
        errors=errors,
        contract_metadata=contract_metadata,
        provenance=provenance,
        timestamp=timestamp,
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_result_summary(
    *,
    run_id: str,
    backend: str,
    model_profile_id: str | None,
    problem_id: str | None,
    candidate: dict[str, Any],
    status: str,
    simulation_output: dict[str, Any],
    overall_pass: bool | None = None,
    failure_category: str | None = None,
    verifier_id: str | None = None,
    verifier_result: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    contract_metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    artifacts = simulation_output.get("artifacts") if isinstance(simulation_output, dict) else {}
    simulation_metrics = simulation_output.get("summary_metrics") if isinstance(simulation_output, dict) else {}
    verifier_metrics = verifier_result.get("summary_metrics") if isinstance(verifier_result, dict) else {}
    summary: dict[str, Any] = {
        "run_id": run_id,
        "backend": backend,
        "model_profile_id": model_profile_id,
        "problem_id": problem_id,
        "candidate": copy.deepcopy(candidate),
        "status": status,
        "overall_pass": overall_pass,
        "failure_category": failure_category,
        "verifier_id": verifier_id,
        "artifacts": copy.deepcopy(artifacts) if isinstance(artifacts, dict) else {},
        "summary_metrics": copy.deepcopy(verifier_metrics or simulation_metrics) if isinstance(verifier_metrics or simulation_metrics, dict) else {},
        "simulation_output_summary": _compact_simulation_output(simulation_output),
        "warnings": [str(item) for item in (warnings or [])],
        "errors": [str(item) for item in (errors or [])],
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(contract_metadata, dict):
        summary["contract"] = copy.deepcopy(contract_metadata)
    if provenance:
        summary["provenance"] = copy.deepcopy(provenance)
    for key in ("solution_freshness", "recomputed_solutions", "preflight"):
        if key in simulation_output:
            summary[key] = copy.deepcopy(simulation_output[key])
    if isinstance(verifier_result, dict):
        summary["verifier_result"] = _compact_verifier_result(verifier_result)
    return summary


def load_result_summary(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Run summary must be a JSON object: {path}")
    return payload


def find_latest_result_summary(runs_dir: str | Path) -> Path | None:
    root = Path(runs_dir)
    if not root.exists() or not root.is_dir():
        return None
    summaries = [path for path in root.rglob(RESULT_SUMMARY_FILENAME) if path.is_file()]
    if not summaries:
        return None
    return max(summaries, key=lambda path: path.stat().st_mtime)


def _compact_simulation_output(simulation_output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(simulation_output, dict):
        return {}

    data_by_lam = simulation_output.get("data_by_lam")
    if not isinstance(data_by_lam, dict):
        return {}

    wavelengths = sorted(str(key) for key in data_by_lam)
    sweep_points_by_wavelength: dict[str, int] = {}
    for wavelength, series in data_by_lam.items():
        if isinstance(series, dict):
            values = series.get("param_nm") or series.get("param") or series.get("l") or []
            sweep_points_by_wavelength[str(wavelength)] = len(values) if isinstance(values, list) else 0
        else:
            sweep_points_by_wavelength[str(wavelength)] = 0

    return {
        "wavelengths_present": wavelengths,
        "sweep_points_by_wavelength": sweep_points_by_wavelength,
    }


def _compact_verifier_result(verifier_result: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "overall_pass",
        "summary_metrics",
        "per_condition_results",
        "failure_reason",
        "limiting_constraint",
        "warnings",
        "failure_category",
        "required_outputs",
        "hard_validity",
        "overall_pass_relaxed",
        "overall_pass_nominal",
        "overall_pass_strict",
        "continuous_score",
        "normalized_margins",
        "hard_constraint_margins",
        "agent_feedback",
    }
    return {
        key: _compact_value(value)
        for key, value in verifier_result.items()
        if key in allowed_keys
    }


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 20:
            return {
                "count": len(value),
                "first": _compact_value(value[0]),
                "last": _compact_value(value[-1]),
            }
        return [_compact_value(item) for item in value]
    return copy.deepcopy(value)
