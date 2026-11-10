from __future__ import annotations

import difflib
import math
from collections.abc import Iterable
from typing import Any

from ..schemas.problem_spec import ProblemSpec


SUPPORTED_EXECUTION_BACKENDS = {"mock", "matlab_livelink"}
# Keys the fixed LiveLink adapter applies to the model. ``unapplied_fields`` is
# the explicit list of candidate fields that intentionally never reach COMSOL
# (for example values consumed only by a parser or verifier).
APPLIED_BINDING_KEYS = {"parameters", "tags", "sweeps", "shape_switch", "material_switch", "feature_switches", "outputs"}
KNOWN_BINDING_KEYS = APPLIED_BINDING_KEYS | {"unapplied_fields"}
# Read by the core although ProblemSpec allows other package-owned keys.
KNOWN_PROBLEM_KEYS = set(ProblemSpec.model_fields) | {"thresholds", "preflight", "provenance_files"}


def backend_compatibility_errors(profile: dict[str, Any], backend: str) -> list[str]:
    """A backend may only evaluate profiles declared for it.

    In particular the synthetic mock backend must never produce an "evaluated"
    verdict for a real COMSOL contract.
    """
    requested = str(backend).strip()
    declared = str((profile.get("backend") or {}).get("type") or "").strip()
    if requested in SUPPORTED_EXECUTION_BACKENDS and declared and requested != declared:
        return [
            f"backend={requested!r} cannot evaluate model profile {profile.get('model_profile_id')!r}, "
            f"whose backend.type is {declared!r}."
        ]
    return []


def model_binding_errors(profile: dict[str, Any], schema: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Reject LiveLink contracts whose candidate fields would silently not reach COMSOL."""
    errors: list[str] = []
    bindings = profile.get("model_bindings") or {}
    if not isinstance(bindings, dict):
        return ["model_bindings must be an object."]
    for key in bindings:
        if key not in KNOWN_BINDING_KEYS:
            suggestion = difflib.get_close_matches(str(key), sorted(KNOWN_BINDING_KEYS), n=1, cutoff=0.75)
            if suggestion:
                errors.append(
                    f"model_bindings.{key} is not a recognized binding (did you mean {suggestion[0]!r}?); "
                    "the LiveLink adapter would ignore it."
                )

    properties = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    unapplied = bindings.get("unapplied_fields") or []
    if not isinstance(unapplied, list) or not all(isinstance(item, str) for item in unapplied):
        errors.append("model_bindings.unapplied_fields must be a list of candidate field names.")
        unapplied = []
    for name in unapplied:
        if name not in properties:
            errors.append(f"model_bindings.unapplied_fields lists unknown candidate field {name!r}.")

    parameters = bindings.get("parameters") or {}
    applied = set(parameters) if isinstance(parameters, dict) else set()
    for key in ("shape_switch", "material_switch"):
        entry = bindings.get(key)
        if isinstance(entry, dict) and entry.get("candidate_field"):
            applied.add(str(entry["candidate_field"]))
    for entry in _entries(bindings.get("feature_switches")):
        if entry.get("candidate_field"):
            applied.add(str(entry["candidate_field"]))
    for entry in _entries(bindings.get("sweeps")):
        if str(entry.get("kind") or "") not in {"range", "values"}:
            continue
        for key in ("start_field", "stop_field"):
            if entry.get(key):
                applied.add(str(entry[key]))
        source = str(entry.get("values_from") or "")
        if source.startswith("candidate."):
            applied.add(source.split(".", 2)[1])

    for name in sorted(set(properties) - applied - set(unapplied)):
        errors.append(
            f"Candidate field {name!r} is not applied to the COMSOL model by any model_bindings entry; "
            "bind it, or list it in model_bindings.unapplied_fields if only the parser/verifier uses it."
        )

    if isinstance(parameters, dict):
        for name in parameters:
            if name in candidate:
                value = candidate[name]
                numeric = isinstance(value, bool) or (isinstance(value, (int, float)) and math.isfinite(float(value)))
                if not numeric:
                    errors.append(f"Candidate field {name!r} is bound to a COMSOL parameter and must be a finite number.")
    return errors


def problem_contract_errors(problem: dict[str, Any]) -> list[str]:
    """Report misspelled ProblemSpec keys, which would otherwise be silently ignored."""
    errors: list[str] = []
    for key in problem:
        if key.startswith("_") or key in KNOWN_PROBLEM_KEYS:
            continue
        suggestion = difflib.get_close_matches(str(key), sorted(KNOWN_PROBLEM_KEYS), n=1, cutoff=0.8)
        if suggestion:
            errors.append(f"ProblemSpec field {key!r} is not recognized (did you mean {suggestion[0]!r}?); it would be ignored.")
    return errors


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


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
