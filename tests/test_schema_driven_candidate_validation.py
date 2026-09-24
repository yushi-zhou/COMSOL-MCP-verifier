from __future__ import annotations

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import validate_candidate_payload


def test_external_schema_rejects_unknown_and_out_of_range_fields() -> None:
    packages = PackageRegistry()
    profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)
    candidate = {"width_nm": -1, "gap_nm": 10, "length_um": 2.5, "raw_command": "no"}

    result = validate_candidate_payload(
        "generic_mock_profile",
        "generic_mock_problem",
        candidate,
        profiles,
        problems,
        verifiers,
    )

    assert result["valid"] is False
    assert any("width_nm" in error for error in result["errors"])
    assert any("raw_command" in error for error in result["errors"])
