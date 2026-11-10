from __future__ import annotations

import pytest

from em_design_mcp.execution_policy import estimate_candidate_cost, parse_execution_policy, resolve_execution_policy


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
        "execution_policy": {"allow_real_backend": True, "max_sweep_points": 100},
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


def test_real_backend_requires_explicit_permission() -> None:
    result = estimate_candidate_cost({"execution_policy": {"max_sweep_points": 10}}, {}, {}, backend="matlab_livelink")
    assert result["valid"] is False
    assert any("explicit execution_policy.allow_real_backend: true" in error for error in result["errors"])
    assert estimate_candidate_cost({}, {}, {}, backend="mock")["valid"] is True


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ({"max_sweep_points": "1e3"}, "positive integer"),
        ({"max_sweep_points": 0}, "positive integer"),
        ({"backend_timeout_seconds": "2h"}, "positive integer"),
        ({"max_sweep_points": True}, "positive integer"),
        ({"allow_real_backend": "false"}, "true or false"),
        ({"max_sweep_point": 10}, "did you mean 'max_sweep_points'"),
    ],
)
def test_malformed_policy_fails_closed(raw, fragment) -> None:
    _, errors = parse_execution_policy({"execution_policy": {"allow_real_backend": True, **raw}}, {})
    assert any(fragment in error for error in errors), errors
    assert estimate_candidate_cost({"execution_policy": {"allow_real_backend": True, **raw}}, {}, {})["valid"] is False
    with pytest.raises(ValueError, match="Invalid execution_policy"):
        resolve_execution_policy({"execution_policy": {"allow_real_backend": True, **raw}}, {})


def _values_profile(source: str = "candidate.wavelengths_nm") -> dict:
    return {
        "model_bindings": {"sweeps": [{"kind": "values", "study_tag": "std1", "feature_tag": "param",
                                       "parameter": "lam", "unit": "nm", "values_from": source}]},
        "execution_policy": {"allow_real_backend": True, "max_sweep_points": 10},
    }


def test_nested_sweep_values_count_every_leaf_like_matlab() -> None:
    result = estimate_candidate_cost(_values_profile(), {}, {"wavelengths_nm": [list(range(400, 1400))]})
    assert result["valid"] is False
    assert result["estimated_sweep_points"] == 1000


def test_candidate_sweep_expressions_are_rejected() -> None:
    for values in (["range(400,0.001,800)"], ["500"], [True]):
        result = estimate_candidate_cost(_values_profile(), {}, {"wavelengths_nm": values})
        assert result["valid"] is False, values
        assert any("must be numbers" in error for error in result["errors"]), result["errors"]


def test_trusted_numeric_text_and_flat_values_still_count() -> None:
    problem = {"independent_variables": {"wavelength_nm": ["600", 650, 700.0]}}
    result = estimate_candidate_cost(_values_profile("problem_spec.independent_variables.wavelength_nm"), problem, {})
    assert result["valid"] is True
    assert result["estimated_sweep_points"] == 3


@pytest.mark.parametrize("sweeps", [
    {"angle_sweep": {"kind": "parametric_linspace", "start_field": "a", "stop_field": "b"}},
    [{"kind": "values"}],
    ["not-an-object"],
])
def test_unsupported_or_incomplete_sweeps_fail_before_launch(sweeps) -> None:
    profile = {"model_bindings": {"sweeps": sweeps}, "execution_policy": {"allow_real_backend": True}}
    assert estimate_candidate_cost(profile, {}, {"a": 1, "b": 2})["valid"] is False


def test_named_sweep_mapping_is_explained() -> None:
    profile = {"model_bindings": {"sweeps": {"angle_sweep": {"kind": "parametric_linspace"}}},
               "execution_policy": {"allow_real_backend": True}}
    errors = estimate_candidate_cost(profile, {}, {})["errors"]
    assert any("named entries ['angle_sweep'] (kind parametric_linspace)" in error for error in errors), errors


def test_unbounded_sweeps_are_flagged() -> None:
    profile = _values_profile()
    del profile["execution_policy"]["max_sweep_points"]
    result = estimate_candidate_cost(profile, {}, {"wavelengths_nm": [500, 600]})
    assert result["valid"] is True
    assert any("not bounded" in warning for warning in result["warnings"])
