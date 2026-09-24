from __future__ import annotations

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import evaluate_candidate_payload


def test_evaluate_candidate_returns_mock_result() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {
        "shape": "pillar",
        "material": "GaP",
        "P_nm": 320,
        "H_nm": 430,
        "l_min_nm": 60,
        "l_max_nm": 250,
    }
    result = evaluate_candidate_payload("metaunit_gap_psi_only", "metaunit_phase_coverage", candidate, "mock", model_profiles, problems, verifiers)
    assert result["valid"] is True
    assert result["overall_pass"] is True
    assert "data_by_lam" in result["simulation_output"]
    assert result["verifier_id"] == "mock_metaunit_phase_sweep"
