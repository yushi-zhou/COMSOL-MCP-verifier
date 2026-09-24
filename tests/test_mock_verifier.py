from __future__ import annotations

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import evaluate_candidate_payload


def test_mock_generic_verifier_passes() -> None:
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()

    candidate = {
        "width_nm": 80,
        "gap_nm": 10,
        "length_um": 2.5,
    }
    result = evaluate_candidate_payload("generic_mock_profile", "generic_mock_problem", candidate, "mock", model_profiles, problems, verifiers)
    assert result["overall_pass"] is True
    assert result["verifier_result"]["summary_metrics"]["score"] >= 0
