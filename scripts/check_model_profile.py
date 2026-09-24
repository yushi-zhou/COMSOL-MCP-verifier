from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import estimate_candidate_cost_payload, validate_candidate_payload
from em_design_mcp.utils.dotenv import load_project_dotenv
from em_design_mcp.validation.schema_validation import deep_merge_schema


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


@dataclass(frozen=True)
class CheckReport:
    model_profile_id: str
    problem_id: str
    backend: str
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return not any(check.failed for check in self.checks)


def run_check(
    *,
    model_profile_id: str,
    problem_id: str,
    candidate: dict[str, Any] | None = None,
    backend: str = "matlab_livelink",
) -> CheckReport:
    packages = PackageRegistry()
    model_profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)
    checks: list[Check] = []

    profile: dict[str, Any] | None = None
    problem: dict[str, Any] | None = None
    verifier_entry: Any | None = None

    try:
        profile = model_profiles.as_dict(model_profile_id)
        checks.append(Check("profile exists", "PASS", f"loaded {model_profile_id}"))
    except Exception as exc:
        checks.append(Check("profile exists", "FAIL", str(exc)))

    try:
        problem = problems.as_dict(problem_id)
        checks.append(Check("problem exists", "PASS", f"loaded {problem_id}"))
    except Exception as exc:
        checks.append(Check("problem exists", "FAIL", str(exc)))

    if profile is not None and problem is not None:
        checks.append(_check_profile_problem_pair(profile, problem))
    else:
        checks.append(Check("profile/problem compatibility", "SKIP", "requires profile and problem"))

    if problem is not None:
        verifier_id = str(problem.get("verifier_id") or "").strip()
        try:
            verifier_entry = verifiers.get(verifier_id)
            checks.append(Check("verifier exists", "PASS", verifier_id))
        except Exception as exc:
            checks.append(Check("verifier exists", "FAIL", str(exc)))
    else:
        checks.append(Check("verifier exists", "SKIP", "requires problem"))

    if profile is not None and problem is not None:
        checks.append(_check_expected_outputs(profile, problem))
    else:
        checks.append(Check("expected outputs compatible", "SKIP", "requires profile and problem"))

    if profile is not None and verifier_entry is not None:
        checks.append(_check_verifier_outputs(profile, verifier_entry))
    else:
        checks.append(Check("verifier outputs compatible", "SKIP", "requires profile and verifier"))

    if profile is not None:
        checks.append(_check_parser(profile, verifiers))
    else:
        checks.append(Check("parser recognized", "SKIP", "requires profile"))

    if profile is not None and problem is not None:
        checks.append(_check_candidate_schema(profile, problem))
    else:
        checks.append(Check("candidate schema available", "SKIP", "requires profile and problem"))

    if candidate is None:
        checks.append(Check("candidate validates", "SKIP", "no --candidate-json provided"))
        checks.append(Check("candidate cost estimate", "SKIP", "no --candidate-json provided"))
    elif profile is not None and problem is not None:
        checks.append(_check_candidate_validation(model_profile_id, problem_id, candidate, model_profiles, problems, verifiers))
        checks.append(_check_candidate_cost(model_profile_id, problem_id, candidate, backend, model_profiles, problems, verifiers))
    else:
        checks.append(Check("candidate validates", "SKIP", "requires profile and problem"))
        checks.append(Check("candidate cost estimate", "SKIP", "requires profile and problem"))

    return CheckReport(
        model_profile_id=model_profile_id,
        problem_id=problem_id,
        backend=backend,
        checks=checks,
    )


def print_report(report: CheckReport) -> None:
    print("Model onboarding check")
    print(f"profile: {report.model_profile_id}")
    print(f"problem: {report.problem_id}")
    print(f"backend: {report.backend}")
    for check in report.checks:
        suffix = f": {check.detail}" if check.detail else ""
        print(f"[{check.status}] {check.name}{suffix}")
    print(f"Result: {'PASS' if report.passed else 'FAIL'}")


def parse_candidate_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--candidate-json must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--candidate-json must decode to a JSON object.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    load_project_dotenv()
    args = _parse_args(argv)
    try:
        candidate = parse_candidate_json(args.candidate_json)
    except ValueError as exc:
        report = CheckReport(
            model_profile_id=args.model_profile_id,
            problem_id=args.problem_id,
            backend=args.backend,
            checks=[Check("candidate JSON", "FAIL", str(exc))],
        )
        print_report(report)
        return 1

    report = run_check(
        model_profile_id=args.model_profile_id,
        problem_id=args.problem_id,
        candidate=candidate,
        backend=args.backend,
    )
    print_report(report)
    return 0 if report.passed else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Statically check a model profile/problem pair before real COMSOL onboarding.",
    )
    parser.add_argument("--model-profile-id", required=True)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--candidate-json")
    parser.add_argument("--backend", default="matlab_livelink")
    return parser.parse_args(argv)


def _check_profile_problem_pair(profile: dict[str, Any], problem: dict[str, Any]) -> Check:
    errors: list[str] = []
    family = problem.get("family")
    profile_id = profile.get("model_profile_id")
    if family not in (profile.get("compatible_problem_families") or []):
        errors.append(f"problem family {family!r} is not in profile compatible_problem_families")
    if profile_id not in (problem.get("compatible_model_profiles") or []):
        errors.append(f"profile {profile_id!r} is not in problem compatible_model_profiles")
    if errors:
        return Check("profile/problem compatibility", "FAIL", _join_messages(errors))
    return Check("profile/problem compatibility", "PASS", f"family={family!r}, profile={profile_id!r}")


def _check_expected_outputs(profile: dict[str, Any], problem: dict[str, Any]) -> Check:
    output_names = _collect_output_names(profile.get("output_schema") or {})
    missing = [name for name in (problem.get("expected_outputs") or []) if str(name) not in output_names]
    if missing:
        return Check("expected outputs compatible", "FAIL", f"missing from output_schema: {missing}")
    return Check("expected outputs compatible", "PASS", f"expected_outputs={problem.get('expected_outputs') or []}")


def _check_verifier_outputs(profile: dict[str, Any], verifier_entry: Any) -> Check:
    output_names = _collect_output_names(profile.get("output_schema") or {})
    missing = [name for name in verifier_entry.required_outputs if str(name) not in output_names]
    if missing:
        return Check("verifier outputs compatible", "FAIL", f"missing from output_schema: {missing}")
    return Check("verifier outputs compatible", "PASS", f"required_outputs={verifier_entry.required_outputs}")


def _check_parser(profile: dict[str, Any], verifiers: VerifierRegistry) -> Check:
    outputs = (profile.get("model_bindings") or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        return Check("parser recognized", "FAIL", "model_bindings.outputs must be an object when present")
    parser_name = str(outputs.get("parser") or "comsol_table").strip()
    if parser_name != "comsol_table":
        try:
            verifiers.plugins.get("parsers", parser_name)
        except Exception as exc:
            return Check("parser recognized", "FAIL", str(exc))
    detail = f"{parser_name}"
    if "parser" not in outputs:
        detail += " (default)"
    return Check("parser recognized", "PASS", detail)


def _check_candidate_schema(profile: dict[str, Any], problem: dict[str, Any]) -> Check:
    try:
        schema = deep_merge_schema(profile["design_schema"], problem.get("candidate_schema_overrides"))
    except Exception as exc:
        return Check("candidate schema available", "FAIL", str(exc))
    required = schema.get("required") or []
    return Check("candidate schema available", "PASS", f"required={required}")


def _check_candidate_validation(
    model_profile_id: str,
    problem_id: str,
    candidate: dict[str, Any],
    model_profiles: ModelProfileRegistry,
    problems: ProblemSpecRegistry,
    verifiers: VerifierRegistry,
) -> Check:
    result = validate_candidate_payload(model_profile_id, problem_id, candidate, model_profiles, problems, verifiers)
    if result["valid"]:
        return Check("candidate validates", "PASS")
    return Check("candidate validates", "FAIL", _join_messages(result.get("errors") or ["candidate validation failed"]))


def _check_candidate_cost(
    model_profile_id: str,
    problem_id: str,
    candidate: dict[str, Any],
    backend: str,
    model_profiles: ModelProfileRegistry,
    problems: ProblemSpecRegistry,
    verifiers: VerifierRegistry,
) -> Check:
    result = estimate_candidate_cost_payload(model_profile_id, problem_id, candidate, backend, model_profiles, problems, verifiers)
    detail = (
        f"estimated_sweep_points={result.get('estimated_sweep_points')}, "
        f"estimated_conditions={result.get('estimated_conditions')}, "
        f"estimated_geometry_points={result.get('estimated_geometry_points')}"
    )
    if result["valid"]:
        return Check("candidate cost estimate", "PASS", detail)
    errors = _join_messages(result.get("errors") or ["cost estimate failed"])
    return Check("candidate cost estimate", "FAIL", f"{detail}; {errors}")


def _collect_output_names(output_schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    names.update(str(item) for item in (output_schema.get("required") or []))
    properties = output_schema.get("properties") or {}
    if isinstance(properties, dict):
        names.update(str(item) for item in properties.keys())
    return names


def _join_messages(messages: list[Any]) -> str:
    return "; ".join(str(message) for message in messages if str(message))


if __name__ == "__main__":
    raise SystemExit(main())
