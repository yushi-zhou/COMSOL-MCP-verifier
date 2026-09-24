from __future__ import annotations

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import validate_candidate_payload


def test_problem_requiring_data_by_lam_fails_with_generic_profile() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}
    result = validate_candidate_payload("generic_mock_profile", "metaunit_phase_coverage", candidate, model_profiles, problems, verifiers)

    assert result["valid"] is False
    assert any("Problem expected output 'data_by_lam'" in error for error in result["errors"])


def test_unknown_verifier_id_fails_validation_clearly() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}
    problem = problems.as_dict("generic_mock_problem")
    problem["verifier_id"] = "unknown_verifier"

    # Use the same candidate/tool path but with an injected problem spec via a temp registry-like shim.
    class ShimProblemRegistry:
        def as_dict(self, problem_id: str):
            return problem

    result = validate_candidate_payload("generic_mock_profile", "generic_mock_problem", candidate, model_profiles, ShimProblemRegistry(), verifiers)  # type: ignore[arg-type]
    assert result["valid"] is False
    assert any("Unknown verifier_id" in error for error in result["errors"])


def test_existing_valid_pairs_still_pass() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    metaunit_candidate = {"shape": "pillar", "material": "GaP", "P_nm": 320, "H_nm": 430, "l_min_nm": 60, "l_max_nm": 250}
    generic_candidate = {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}

    metaunit_result = validate_candidate_payload("metaunit_gap_psi_only", "metaunit_phase_coverage", metaunit_candidate, model_profiles, problems, verifiers)
    generic_result = validate_candidate_payload("generic_mock_profile", "generic_mock_problem", generic_candidate, model_profiles, problems, verifiers)

    assert metaunit_result["valid"] is True
    assert generic_result["valid"] is True
