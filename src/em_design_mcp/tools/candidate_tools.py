from __future__ import annotations

import os
import json
from typing import Any

from ..backends.backend_factory import create_backend
from ..backends.base import BackendConfigurationError, BackendError
from ..execution_policy import estimate_candidate_cost as estimate_cost_from_policy
from ..registries.model_profile_registry import ModelProfileRegistry
from ..registries.problem_spec_registry import ProblemSpecRegistry
from ..registries.verifier_registry import VerifierRegistry
from ..runs.result_summary import write_result_summary
from ..utils.contract_metadata import build_contract_metadata, contract_thresholds
from ..utils.paths import RUNS_DIR_ENV, configured_run_root
from ..utils.provenance import capture_provenance, compact_provenance, file_sha256, require_provenance
from ..schemas.model_observation import selected_measurements
from ..validation.physics_preflight import check_topics
from ..utils.run_ids import make_run_id
from ..validation.compatibility import check_profile_problem_compatibility
from ..validation.constraint_validation import validate_constraints
from ..validation.schema_validation import deep_merge_schema, validate_against_schema


def get_contract_bundle_payload(model_profile_id: str, problem_id: str, model_profiles: ModelProfileRegistry, problems: ProblemSpecRegistry, verifiers: VerifierRegistry) -> dict[str, Any]:
    profile = model_profiles.as_dict(model_profile_id)
    problem = problems.as_dict(problem_id)
    effective_schema = deep_merge_schema(profile["design_schema"], problem.get("candidate_schema_overrides"))
    verifier_entry = verifiers.get(str(problem.get("verifier_id") or ""))
    contract_metadata = build_contract_metadata(
        profile,
        problem,
        verifier_id=verifier_entry.verifier_id,
        verifier_version=verifier_entry.version,
    )

    return {
        "model_profile_id": model_profile_id,
        "problem_id": problem_id,
        "profile_version": contract_metadata["model_profile_version"],
        "problem_version": contract_metadata["problem_version"],
        "verifier_version": contract_metadata["verifier_version"],
        "contract_hash": contract_metadata["contract_hash"],
        "contract_hash_algorithm": contract_metadata["contract_hash_algorithm"],
        "profile_summary": _profile_contract_summary(profile, effective_schema),
        "problem_summary": _problem_contract_summary(problem),
        "effective_candidate_schema": effective_schema,
        "thresholds": contract_thresholds(problem),
        "expected_outputs": list(problem.get("expected_outputs") or []),
        "verifier_summary": {
            "verifier_id": verifier_entry.verifier_id,
            "version": verifier_entry.version,
            "required_outputs": list(verifier_entry.required_outputs),
            "description": verifier_entry.description,
        },
        "measurements": selected_measurements(profile),
        "preflight": list(profile.get("preflight") or []) + list(problem.get("preflight") or []),
        "provenance": compact_provenance(capture_provenance(profile, problem, verifiers.packages)),
    }


def validate_candidate_payload(model_profile_id: str, problem_id: str, candidate: dict[str, Any], model_profiles: ModelProfileRegistry, problems: ProblemSpecRegistry, verifiers: VerifierRegistry) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    profile = problem = None
    verifier_entry = None
    try:
        profile = model_profiles.as_dict(model_profile_id)
    except Exception as exc:
        errors.append(str(exc))
    try:
        problem = problems.as_dict(problem_id)
    except Exception as exc:
        errors.append(str(exc))

    applied_schema: dict[str, Any] | None = None
    applied_constraints: list[dict[str, Any]] = []
    normalized_candidate: dict[str, Any] | None = None

    if profile and problem:
        try:
            check_topics(list(profile.get("preflight") or []) + list(problem.get("preflight") or []))
            selected_measurements(profile)
        except ValueError as exc:
            errors.append(str(exc))
        verifier_required_outputs: list[str] | None = None
        verifier_id = str(problem.get("verifier_id", "")).strip()
        if verifier_id:
            try:
                verifier_entry = verifiers.get(verifier_id)
                verifier_required_outputs = list(verifier_entry.required_outputs)
            except Exception as exc:
                errors.append(str(exc))

        compatible, compatibility_errors, compatibility_warnings = check_profile_problem_compatibility(
            profile,
            problem,
            verifier_required_outputs=verifier_required_outputs,
        )
        if not compatible:
            errors.extend(compatibility_errors)
        warnings.extend(compatibility_warnings)

        applied_schema = deep_merge_schema(profile["design_schema"], problem.get("candidate_schema_overrides"))
        schema_valid, schema_errors, normalized_candidate = validate_against_schema(candidate, applied_schema)
        if not schema_valid:
            errors.extend(schema_errors)

        applied_constraints = list(problem.get("constraints", []))
        if schema_valid:
            constraint_result = validate_constraints(candidate, applied_constraints)
            errors.extend(constraint_result.errors)
            warnings.extend(constraint_result.warnings)

            if verifier_entry is not None:
                precheck_constraints = getattr(verifier_entry, "precheck_constraints", None)
                if precheck_constraints:
                    precheck = validate_constraints(candidate, precheck_constraints)
                    errors.extend(precheck.errors)
                    warnings.extend(precheck.warnings)

    valid = len(errors) == 0
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "normalized_candidate": normalized_candidate if normalized_candidate is not None else candidate,
        "applied_schema": applied_schema,
        "applied_constraints": applied_constraints,
    }


def estimate_candidate_cost_payload(model_profile_id: str, problem_id: str, candidate: dict[str, Any], backend: str, model_profiles: ModelProfileRegistry, problems: ProblemSpecRegistry, verifiers: VerifierRegistry) -> dict[str, Any]:
    validation = validate_candidate_payload(model_profile_id, problem_id, candidate, model_profiles, problems, verifiers)
    normalized_candidate = validation["normalized_candidate"]
    warnings = list(validation["warnings"])
    errors = list(validation["errors"])

    profile = problem = None
    try:
        profile = model_profiles.as_dict(model_profile_id)
    except Exception as exc:
        if str(exc) not in errors:
            errors.append(str(exc))
    try:
        problem = problems.as_dict(problem_id)
    except Exception as exc:
        if str(exc) not in errors:
            errors.append(str(exc))

    if profile is None or problem is None:
        return {
            "valid": False,
            "estimated_sweep_points": None,
            "estimated_conditions": None,
            "estimated_geometry_points": None,
            "warnings": warnings,
            "errors": errors,
            "policy_applied": {},
            "validation": validation,
        }

    cost_estimate = estimate_cost_from_policy(profile, problem, normalized_candidate, backend=backend)
    return {
        **cost_estimate,
        "valid": bool(validation["valid"] and cost_estimate["valid"]),
        "warnings": warnings + list(cost_estimate["warnings"]),
        "errors": errors + list(cost_estimate["errors"]),
        "validation": validation,
    }


def evaluate_candidate_payload(
    model_profile_id: str,
    problem_id: str,
    candidate: dict[str, Any],
    backend: str,
    model_profiles: ModelProfileRegistry,
    problems: ProblemSpecRegistry,
    verifiers: VerifierRegistry,
    *,
    run_id_override: str | None = None,
    expected_provenance: dict | str | None = None,
) -> dict[str, Any]:
    validation = validate_candidate_payload(model_profile_id, problem_id, candidate, model_profiles, problems, verifiers)
    normalized_candidate = validation["normalized_candidate"]
    raw_validation_category = classify_failure_payload(validation).get("failure_category")
    validation_failure_category = raw_validation_category if raw_validation_category not in (None, "unknown_failure") else "parameter_validation_error"
    if not validation["valid"]:
        run_id = run_id_override or make_run_id(model_profile_id, problem_id, backend, candidate)
        return {
            "run_id": run_id,
            "backend": backend,
            "valid": False,
            "overall_pass": False,
            "status": "validation_failed",
            "failure_category": validation_failure_category,
            "verifier_id": None,
            "candidate": normalized_candidate,
            "simulation_output": {},
            "verifier_result": {},
            "validation": validation,
            "warnings": validation["warnings"],
            "errors": validation["errors"],
        }

    profile = model_profiles.as_dict(model_profile_id)
    problem = problems.as_dict(problem_id)
    verifier_entry = verifiers.get(problem["verifier_id"])
    run_id = run_id_override or make_run_id(model_profile_id, problem_id, backend, candidate)
    cost_estimate: dict[str, Any] | None = None
    if str(backend).strip() == "matlab_livelink":
        cost_estimate = estimate_cost_from_policy(profile, problem, normalized_candidate, backend=backend)
        if not cost_estimate["valid"]:
            result = {
                "run_id": run_id,
                "backend": backend,
                "valid": False,
                "overall_pass": False,
                "status": "policy_failed",
                "failure_category": "policy_failed",
                "verifier_id": problem.get("verifier_id"),
                "candidate": normalized_candidate,
                "simulation_output": {},
                "verifier_result": {},
                "validation": validation,
                "cost_estimate": cost_estimate,
                "warnings": validation["warnings"] + list(cost_estimate["warnings"]),
                "errors": validation["errors"] + list(cost_estimate["errors"]),
            }
            return _finalize_result(result, profile, problem, verifier_version=verifier_entry.version)

    timeout_seconds = None
    if cost_estimate is not None:
        timeout_seconds = cost_estimate.get("policy_applied", {}).get("backend_timeout_seconds")
    try:
        backend_runner = create_backend(
            backend,
            timeout_seconds=timeout_seconds,
            parser_registry=verifiers.plugins,
        )
    except BackendConfigurationError as exc:
        result = {
            "run_id": run_id,
            "backend": backend,
            "valid": False,
            "overall_pass": False,
            "status": "backend_not_implemented",
            "failure_category": "backend_not_implemented",
            "verifier_id": None,
            "candidate": normalized_candidate,
            "simulation_output": {},
            "verifier_result": {},
            "validation": validation,
            "warnings": validation["warnings"] + exc.warnings,
            "errors": [str(exc)],
        }
        return _finalize_result(result, profile, problem, verifier_version=verifier_entry.version)

    provenance = None
    try:
        provenance = capture_provenance(profile, problem, verifiers.packages)
        require_provenance(expected_provenance, provenance)
        if run_id_override is None:
            run_id = make_run_id(model_profile_id, problem_id, backend, normalized_candidate, provenance["id"])
        if backend == "matlab_livelink" or RUNS_DIR_ENV in os.environ:
            run_dir = configured_run_root(profile) / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        simulation_output = backend_runner.run(model_profile=profile, problem_spec=problem, candidate=normalized_candidate, run_id=run_id)
        require_provenance(provenance, capture_provenance(profile, problem, verifiers.packages))
        artifacts = simulation_output.get("artifacts") or {}
        if artifacts.get("solved_model_path"):
            artifacts["solved_model_sha256"] = file_sha256(artifacts["solved_model_path"])
        simulation_output["solution_freshness"] = (
            "named_measurement_solutions_recomputed" if simulation_output.get("recomputed_solutions")
            else "unverified_legacy_outputs"
        ) if backend == "matlab_livelink" else "synthetic"
    except BackendError as exc:
        result = {
            "run_id": run_id,
            "backend": backend,
            "valid": True,
            "overall_pass": False,
            "status": "stale_provenance" if exc.failure_category == "stale_provenance" else "backend_failed",
            "failure_category": exc.failure_category,
            "verifier_id": problem.get("verifier_id"),
            "candidate": normalized_candidate,
            "simulation_output": {},
            "verifier_result": {},
            "validation": validation,
            "cost_estimate": cost_estimate,
            "provenance": provenance,
            "warnings": validation["warnings"] + exc.warnings,
            "errors": validation["errors"] + [str(exc)],
        }
        return _finalize_result(result, profile, problem, verifier_version=verifier_entry.version)
    verifier_result = verifier_entry.verify(problem, profile, normalized_candidate, simulation_output)
    try:
        require_provenance(provenance, capture_provenance(profile, problem, verifiers.packages))
    except BackendError as exc:
        return {"run_id": run_id, "status": "stale_provenance", "overall_pass": False, "provenance": provenance,
                "failure_category": exc.failure_category, "errors": [str(exc)], "simulation_output": simulation_output}
    overall_pass = bool(verifier_result.get("overall_pass"))
    backend_warnings = getattr(backend_runner, "warnings", [])
    result = {
        "run_id": run_id,
        "backend": backend,
        "valid": True,
        "overall_pass": overall_pass,
        "status": "evaluated" if overall_pass else "verifier_failed",
        "failure_category": None if overall_pass else verifier_result.get("failure_category") or "mixed",
        "verifier_id": problem["verifier_id"],
        "candidate": normalized_candidate,
        "provenance": provenance,
        "simulation_output": simulation_output,
        "verifier_result": verifier_result,
        "validation": validation,
        "cost_estimate": cost_estimate,
        "warnings": validation["warnings"] + list(backend_warnings) + list(verifier_result.get("warnings", [])),
        "errors": validation["errors"] + ([verifier_result.get("failure_reason")] if not overall_pass and verifier_result.get("failure_reason") else []),
    }
    return _finalize_result(result, profile, problem, verifier_version=verifier_entry.version)


def classify_failure_payload(error_message_or_result: Any) -> dict[str, Any]:
    if isinstance(error_message_or_result, dict):
        if error_message_or_result.get("failure_category"):
            return {"failure_category": error_message_or_result.get("failure_category")}
        if error_message_or_result.get("status") == "backend_not_implemented":
            return {"failure_category": "backend_not_implemented"}
        if error_message_or_result.get("status") == "validation_failed":
            return {"failure_category": "parameter_validation_error"}
        if error_message_or_result.get("status") == "policy_failed":
            return {"failure_category": "policy_failed"}
        if error_message_or_result.get("status") == "verifier_failed":
            return {"failure_category": error_message_or_result.get("failure_category") or "mixed"}
        if error_message_or_result.get("status") == "backend_failed":
            return {"failure_category": error_message_or_result.get("failure_category") or "unknown_failure"}

    text = str(error_message_or_result).lower()
    if "missing required" in text or "missing field" in text:
        category = "parameter_validation_error"
    elif "unsupported backend" in text:
        category = "backend_not_implemented"
    elif "incompatible" in text:
        category = "model_profile_incompatible"
    elif "required output" in text:
        category = "missing_required_output"
    elif "constraint" in text:
        category = "parameter_validation_error"
    else:
        category = "unknown_failure"
    return {"failure_category": category}


def _write_final_result_summary_if_enabled(
    result: dict[str, Any],
    profile: dict[str, Any],
    problem: dict[str, Any],
    *,
    verifier_version: str | None = None,
) -> str | None:
    backend = str(result.get("backend") or "")
    if backend != "matlab_livelink" and RUNS_DIR_ENV not in os.environ:
        return None

    try:
        write_result_summary(
            run_dir=configured_run_root(profile) / str(result["run_id"]),
            run_id=str(result["run_id"]),
            backend=backend,
            model_profile_id=str(profile.get("model_profile_id") or ""),
            problem_id=str(problem.get("problem_id") or ""),
            candidate=result.get("candidate") or {},
            status=str(result.get("status") or ""),
            overall_pass=bool(result.get("overall_pass")),
            failure_category=result.get("failure_category"),
            verifier_id=result.get("verifier_id"),
            simulation_output=result.get("simulation_output") or {},
            verifier_result=result.get("verifier_result") or {},
            warnings=result.get("warnings") or [],
            errors=result.get("errors") or [],
            provenance=compact_provenance(result.get("provenance") or {}),
            contract_metadata=build_contract_metadata(
                profile,
                problem,
                verifier_id=result.get("verifier_id"),
                verifier_version=verifier_version,
            ),
        )
    except Exception as exc:
        return f"Failed to write result summary: {exc}"
    return None


def _finalize_result(
    result: dict[str, Any],
    profile: dict[str, Any],
    problem: dict[str, Any],
    *,
    verifier_version: str | None = None,
) -> dict[str, Any]:
    summary_warning = _write_final_result_summary_if_enabled(
        result,
        profile,
        problem,
        verifier_version=verifier_version,
    )
    if summary_warning:
        result.setdefault("warnings", []).append(summary_warning)
    return result


def _profile_contract_summary(profile: dict[str, Any], effective_schema: dict[str, Any]) -> dict[str, Any]:
    backend = profile.get("backend") or {}
    model_bindings = profile.get("model_bindings") or {}
    outputs = model_bindings.get("outputs") or {}
    candidate_fields = sorted((effective_schema.get("properties") or {}).keys())
    return {
        "model_profile_id": profile.get("model_profile_id"),
        "version": profile.get("version"),
        "description": profile.get("description"),
        "domain": profile.get("domain"),
        "backend_type": backend.get("type"),
        "compatible_problem_families": list(profile.get("compatible_problem_families") or []),
        "candidate_fields": candidate_fields,
        "required_candidate_fields": list(effective_schema.get("required") or []),
        "outputs": outputs if isinstance(outputs, dict) else {},
        "execution_policy": profile.get("execution_policy") or {},
    }


def _problem_contract_summary(problem: dict[str, Any]) -> dict[str, Any]:
    return {
        "problem_id": problem.get("problem_id"),
        "version": problem.get("version"),
        "description": problem.get("description"),
        "family": problem.get("family"),
        "difficulty": problem.get("difficulty"),
        "compatible_model_profiles": list(problem.get("compatible_model_profiles") or []),
        "verifier_id": problem.get("verifier_id"),
        "independent_variables": problem.get("independent_variables") or {},
        "objectives": list(problem.get("objectives") or []),
        "constraints": list(problem.get("constraints") or []),
        "execution_policy": problem.get("execution_policy") or {},
    }
