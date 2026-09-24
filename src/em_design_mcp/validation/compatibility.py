from __future__ import annotations

from collections.abc import Iterable


SUPPORTED_EXECUTION_BACKENDS = {"mock", "matlab_livelink"}


def check_profile_problem_compatibility(profile: dict, problem: dict, verifier_required_outputs: Iterable[str] | None = None) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    backend_type = str(profile.get("backend", {}).get("type", "")).strip()
    if backend_type and backend_type not in SUPPORTED_EXECUTION_BACKENDS:
        warnings.append(f"Model profile backend type {backend_type!r} is not supported.")

    if problem.get("family") not in profile.get("compatible_problem_families", []):
        errors.append(
            f"Problem family {problem.get('family')!r} is not compatible with model profile {profile.get('model_profile_id')!r}."
        )
    if profile.get("model_profile_id") not in problem.get("compatible_model_profiles", []):
        errors.append(
            f"Model profile {profile.get('model_profile_id')!r} is not listed in compatible_model_profiles for problem {problem.get('problem_id')!r}."
        )

    profile_outputs = _collect_output_names(profile.get("output_schema", {}))
    problem_expected_outputs = [str(item) for item in problem.get("expected_outputs", [])]
    for expected_output in problem_expected_outputs:
        if expected_output not in profile_outputs:
            errors.append(
                f"Problem expected output {expected_output!r} is not present in model profile output_schema."
            )

    if verifier_required_outputs is not None:
        verifier_outputs = [str(item) for item in verifier_required_outputs]
        for required_output in verifier_outputs:
            if required_output not in profile_outputs:
                errors.append(
                    f"Verifier required output {required_output!r} is not present in model profile output_schema."
                )
        for expected_output in problem_expected_outputs:
            if expected_output not in verifier_outputs:
                errors.append(
                    f"Problem expected output {expected_output!r} is not supported by the selected verifier."
                )

    return len(errors) == 0, errors, warnings


def _collect_output_names(output_schema: dict) -> set[str]:
    names: set[str] = set()
    names.update(str(item) for item in (output_schema.get("required", []) or []))
    names.update(str(item) for item in (output_schema.get("properties", {}) or {}).keys())
    return names
