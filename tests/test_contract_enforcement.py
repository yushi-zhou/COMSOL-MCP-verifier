from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from em_design_mcp.backends.matlab_livelink_backend import MatlabLiveLinkBackend
from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools import candidate_tools
from em_design_mcp.validation.schema_validation import validate_against_schema

VERIFIERS = {
    "pass_verifier": "def verify(problem, profile, candidate, output):\n    return {'overall_pass': True, 'summary_metrics': {'ok': 1}}\n",
    "raising_verifier": "def verify(problem, profile, candidate, output):\n    raise ZeroDivisionError('verifier bug')\n",
    "string_verdict_verifier": "def verify(problem, profile, candidate, output):\n    return {'overall_pass': 'false'}\n",
}


def livelink_profile(**overrides) -> dict:
    profile = {
        "model_profile_id": "live_profile",
        "version": "1",
        "domain": "test",
        "description": "LiveLink contract used by enforcement tests.",
        "backend": {"type": "matlab_livelink", "model_artifact": {"kind": "mph", "path": "model.mph"}},
        "compatible_problem_families": ["fam"],
        "design_schema": {
            "type": "object",
            "properties": {"gap_nm": {"type": "number", "minimum": 10, "maximum": 100}},
            "additionalProperties": False,
        },
        "model_bindings": {"parameters": {"gap_nm": {"comsol_parameter": "gap", "unit": "nm"}}, "tags": {"study": "std1"}},
        "output_schema": {"type": "object", "properties": {}},
        "execution_policy": {"allow_real_backend": True, "max_sweep_points": 5},
    }
    profile.update(overrides)
    return profile


def problem_spec(problem_id: str = "live_problem", verifier_id: str = "pass_verifier", **extra) -> dict:
    return {
        "problem_id": problem_id,
        "version": "1",
        "family": "fam",
        "difficulty": "x",
        "description": "x",
        "compatible_model_profiles": ["live_profile"],
        "independent_variables": {},
        "verifier_id": verifier_id,
        "expected_outputs": [],
        **extra,
    }


@pytest.fixture
def make_package(tmp_path, monkeypatch):
    def build(profile: dict, problems: list[dict]):
        root = tmp_path / "package"
        for folder in ("profiles", "problems", "plugins"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        (root / "model.mph").write_bytes(b"opaque model")
        manifest = {
            "schema_version": "em_design_package_v1",
            "package_id": "contract-tests",
            "profiles": ["profiles/*.yaml"],
            "problems": ["problems/*.yaml"],
            "plugins": {"verifiers": {
                name: {"path": f"plugins/{name}.py", "callable": "verify", "required_outputs": []} for name in VERIFIERS
            }},
        }
        (root / "em-design-package.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        for name, body in VERIFIERS.items():
            (root / "plugins" / f"{name}.py").write_text(body, encoding="utf-8")
        (root / "profiles" / "profile.yaml").write_text(yaml.safe_dump(profile), encoding="utf-8")
        for problem in problems:
            (root / "problems" / f"{problem['problem_id']}.yaml").write_text(yaml.safe_dump(problem), encoding="utf-8")
        monkeypatch.setenv("EM_DESIGN_PACKAGE_ROOTS", str(root))
        monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))
        packages = PackageRegistry()
        return ModelProfileRegistry(packages=packages), ProblemSpecRegistry(packages=packages), VerifierRegistry(packages)

    return build


def validate(registries, candidate, problem_id="live_problem"):
    profiles, problems, verifiers = registries
    return candidate_tools.validate_candidate_payload("live_profile", problem_id, candidate, profiles, problems, verifiers)


# ------------------------------------------------------------------ schema subset

def test_defaults_are_applied_and_validated() -> None:
    schema = {"type": "object", "properties": {"gap_nm": {"type": "number", "minimum": 10, "default": 50}}}
    ok, errors, normalized = validate_against_schema({}, schema)
    assert ok and normalized == {"gap_nm": 50}
    bad = {"type": "object", "properties": {"gap_nm": {"type": "number", "minimum": 10, "default": 1}}}
    assert validate_against_schema({}, bad)[0] is False


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ({"type": "boolean"}, "yes", "must be a boolean"),
        ({"type": "array", "items": {"type": "number"}}, [1, "2"], "[1] must be a number"),
        ({"type": "array", "maxItems": 2}, [1, 2, 3], "at most 2 items"),
        ({"type": "array"}, [1.0, math.nan], "must be finite"),
        ({"type": "string", "pattern": "^[a-z]+$"}, "Abc", "must match pattern"),
        ({"enum": [0, 1]}, True, "must be one of"),
        ({"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}, {}, "Missing required field: f.x"),
        ({"oneOf": [{"type": "number"}]}, 1, "unsupported schema keyword 'oneOf'"),
        ({"type": "bool"}, True, "unsupported schema type"),
    ],
)
def test_schema_keywords_are_enforced_or_rejected(field, value, fragment) -> None:
    ok, errors, _ = validate_against_schema({"f": value}, {"type": "object", "properties": {"f": field}})
    assert ok is False
    assert any(fragment in error for error in errors), errors


def test_annotations_and_unions_are_accepted() -> None:
    schema = {"type": "object", "properties": {"f": {"type": ["number", "null"], "unit": "nm", "description": "x"}}}
    assert validate_against_schema({"f": None}, schema)[0] is True
    assert validate_against_schema({"f": 2.5}, schema)[0] is True


# ------------------------------------------------------------------ bindings and contract keys

def test_unbound_candidate_field_is_rejected_for_livelink(make_package) -> None:
    profile = livelink_profile(model_bindings={"parameter": {"gap_nm": "gap"}, "tags": {"study": "std1"}})
    result = validate(make_package(profile, [problem_spec()]), {"gap_nm": 20})
    assert result["valid"] is False
    assert any("did you mean 'parameters'" in error for error in result["errors"])
    assert any("'gap_nm' is not applied to the COMSOL model" in error for error in result["errors"])


def test_unapplied_fields_must_be_declared_explicitly(make_package) -> None:
    profile = livelink_profile()
    profile["design_schema"]["properties"]["target_nm"] = {"type": "number", "minimum": 0, "maximum": 1}
    profile["model_bindings"]["unapplied_fields"] = ["target_nm"]
    assert validate(make_package(profile, [problem_spec()]), {"gap_nm": 20, "target_nm": 0.5})["valid"] is True


def test_unknown_unapplied_field_and_package_annotations(make_package) -> None:
    profile = livelink_profile()
    profile["model_bindings"]["unapplied_fields"] = ["typo_field"]
    profile["model_bindings"]["illumination"] = {"note": "package-owned annotation"}
    result = validate(make_package(profile, [problem_spec()]), {"gap_nm": 20})
    assert result["valid"] is False
    assert result["errors"] == ["model_bindings.unapplied_fields lists unknown candidate field 'typo_field'."]


def test_parameter_bound_field_must_be_numeric(make_package) -> None:
    profile = livelink_profile()
    profile["design_schema"]["properties"]["gap_nm"] = {"description": "typeless field"}
    result = validate(make_package(profile, [problem_spec()]), {"gap_nm": "1e9"})
    assert any("must be a finite number" in error for error in result["errors"])


def test_misspelled_problem_key_is_reported(make_package) -> None:
    problems = [
        problem_spec("typo_problem", execution_polcy={"max_sweep_points": 1}),
        problem_spec("annotated_problem", baseline_policy={"note": "package-owned"}),
    ]
    registries = make_package(livelink_profile(), problems)
    typo = validate(registries, {"gap_nm": 20}, "typo_problem")
    assert any("did you mean 'execution_policy'" in error for error in typo["errors"])
    assert validate(registries, {"gap_nm": 20}, "annotated_problem")["valid"] is True


def test_mock_backend_cannot_evaluate_livelink_profile(make_package) -> None:
    profiles, problems, verifiers = make_package(livelink_profile(), [problem_spec()])
    estimate = candidate_tools.estimate_candidate_cost_payload(
        "live_profile", "live_problem", {"gap_nm": 20}, "mock", profiles, problems, verifiers)
    assert estimate["valid"] is False
    assert any("backend='mock' cannot evaluate" in error for error in estimate["errors"])
    result = candidate_tools.evaluate_candidate_payload(
        "live_profile", "live_problem", {"gap_nm": 20}, "mock", profiles, problems, verifiers)
    assert (result["status"], result["failure_category"], result["overall_pass"]) == (
        "validation_failed", "backend_incompatible", False)


# ------------------------------------------------------------------ truthful failure records

def _fake_livelink(monkeypatch, output: dict | None = None, error: Exception | None = None):
    def runner(command, **kwargs):
        if error is not None:
            raise error
        match = re.search(r"run_em_design_from_json\('([^']+)', '([^']+)'\)", command[2])
        Path(match.group(2)).write_text(json.dumps(output), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "em_design_mcp.tools.candidate_tools.create_backend",
        lambda *args, **kwargs: MatlabLiveLinkBackend(subprocess_runner=runner, parser_registry=kwargs.get("parser_registry")),
    )


def _evaluate(registries, problem_id):
    profiles, problems, verifiers = registries
    return candidate_tools.evaluate_candidate_payload(
        "live_profile", problem_id, {"gap_nm": 20}, "matlab_livelink", profiles, problems, verifiers)


def _summary(tmp_path, result) -> dict:
    return json.loads((tmp_path / "runs" / result["run_id"] / "result_summary.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("verifier_id", "fragment"), [
    ("raising_verifier", "ZeroDivisionError: verifier bug"),
    ("string_verdict_verifier", "overall_pass must be true or false"),
])
def test_verifier_errors_are_never_reported_as_evaluated(tmp_path, monkeypatch, make_package, verifier_id, fragment) -> None:
    registries = make_package(livelink_profile(), [problem_spec("p", verifier_id)])
    _fake_livelink(monkeypatch, {"status": "ok", "simulation_output": {"summary_metrics": {"x": 1}}})
    result = _evaluate(registries, "p")
    assert (result["status"], result["failure_category"], result["overall_pass"]) == ("verifier_failed", "verifier_error", False)
    assert any(fragment in error for error in result["errors"])
    summary = _summary(tmp_path, result)
    assert (summary["status"], summary["overall_pass"]) == ("verifier_failed", False)


def test_passing_verifier_still_evaluates(tmp_path, monkeypatch, make_package) -> None:
    registries = make_package(livelink_profile(), [problem_spec()])
    _fake_livelink(monkeypatch, {"status": "ok", "simulation_output": {"summary_metrics": {"x": 1}}})
    result = _evaluate(registries, "live_problem")
    assert (result["status"], result["overall_pass"]) == ("evaluated", True)
    assert _summary(tmp_path, result)["status"] == "evaluated"


@pytest.mark.parametrize(("output", "error", "category"), [
    ({"simulation_output": {}}, None, "result_parse_error"),
    (None, RuntimeError("adapter bug"), "backend_internal_error"),
])
def test_backend_surprises_are_final_failures(tmp_path, monkeypatch, make_package, output, error, category) -> None:
    registries = make_package(livelink_profile(), [problem_spec()])
    _fake_livelink(monkeypatch, output, error)
    result = _evaluate(registries, "live_problem")
    assert (result["status"], result["failure_category"], result["overall_pass"]) == ("backend_failed", category, False)
    assert _summary(tmp_path, result)["status"] == "backend_failed"
