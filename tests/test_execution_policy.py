from __future__ import annotations

from em_design_mcp.execution_policy import estimate_candidate_cost, resolve_execution_policy


def test_problem_policy_overrides_profile_policy() -> None:
    policy = resolve_execution_policy(
        {"execution_policy": {"max_sweep_points": 1000, "backend_timeout_seconds": 60}},
        {"execution_policy": {"max_sweep_points": 50}},
    )
    assert policy["max_sweep_points"] == 50
    assert policy["backend_timeout_seconds"] == 60


def test_output_sample_count_is_gated_before_real_backend() -> None:
    profile = {
        "model_bindings": {"outputs": {"sample_count_field": "samples"}},
        "execution_policy": {"max_sweep_points": 100},
    }
    valid = estimate_candidate_cost(profile, {}, {"samples": 100})
    invalid = estimate_candidate_cost(profile, {}, {"samples": 101})
    assert valid["valid"] is True
    assert valid["estimated_sweep_points"] == 100
    assert invalid["valid"] is False
    assert "max_sweep_points=100" in invalid["errors"][0]


def test_real_backend_can_be_disabled_by_contract() -> None:
    result = estimate_candidate_cost(
        {"execution_policy": {"allow_real_backend": False}},
        {},
        {},
        backend="matlab_livelink",
    )
    assert result["valid"] is False
    assert any("does not allow" in error for error in result["errors"])
