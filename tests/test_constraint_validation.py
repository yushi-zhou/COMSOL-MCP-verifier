from __future__ import annotations

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import validate_candidate_payload


def test_structural_constraints_are_enforced() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {
        "shape": "pillar",
        "material": "GaP",
        "P_nm": 320,
        "H_nm": 430,
        "l_min_nm": 60,
        "l_max_nm": 318,
    }
    result = validate_candidate_payload("metaunit_gap_psi_only", "metaunit_phase_coverage", candidate, model_profiles, problems, verifiers)
    assert result["valid"] is False
    assert any("inside_period" in error for error in result["errors"])


def test_field_in_constraint_is_enforced() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {
        "width_nm": 80,
        "gap_nm": 12,
        "length_um": 2.5,
    }
    result = validate_candidate_payload("generic_mock_profile", "generic_mock_problem", candidate, model_profiles, problems, verifiers)
    assert result["valid"] is False
    assert any("gap_bounds" in error for error in result["errors"])
