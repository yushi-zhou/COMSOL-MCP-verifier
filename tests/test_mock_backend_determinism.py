from __future__ import annotations

from em_design_mcp.backends.mock_backend import MockBackend


def test_mock_backend_is_deterministic_across_calls() -> None:
    backend = MockBackend()
    profile = {
        "output_schema": {"required": ["data_by_lam"], "properties": {"data_by_lam": {"type": "object"}}},
    }
    problem = {"independent_variables": {"wavelength_nm": [750, 800]}}
    candidate = {"l_min_nm": 50, "l_max_nm": 220}

    first = backend.run(model_profile=profile, problem_spec=problem, candidate=candidate, run_id="run_1")
    second = backend.run(model_profile=profile, problem_spec=problem, candidate=candidate, run_id="run_1")
    third = backend.run(model_profile=profile, problem_spec=problem, candidate={"l_min_nm": 55, "l_max_nm": 220}, run_id="run_1")
    fourth = backend.run(model_profile=profile, problem_spec=problem, candidate=candidate, run_id="run_2")

    assert first == second
    assert first != third
    assert first != fourth


def test_mock_backend_uses_profile_driven_sweep_fields() -> None:
    backend = MockBackend()
    profile = {
        "mock_generation": {
            "sweep": {
                "start_field": "start_um",
                "stop_field": "stop_um",
                "default_start": 1.0,
                "default_stop_offset": 2.0,
                "max_points": 4,
            }
        },
        "output_schema": {"required": ["data_by_lam"], "properties": {"data_by_lam": {"type": "object"}}},
    }
    problem = {"independent_variables": {"wavelength_nm": [750]}}
    candidate = {"start_um": 3.0, "stop_um": 9.0, "bias": 1.5}

    output = backend.run(model_profile=profile, problem_spec=problem, candidate=candidate, run_id="run_1")
    series = output["data_by_lam"]["750"]
    assert series["param_nm"][0] == 3.0
    assert series["param_nm"][-1] == 9.0
    assert len(series["param_nm"]) == 4


def test_mock_backend_fallback_generates_sweep_without_metaunit_fields() -> None:
    backend = MockBackend()
    profile = {
        "output_schema": {"required": ["data_by_lam"], "properties": {"data_by_lam": {"type": "object"}}},
    }
    problem = {"independent_variables": {"wavelength_nm": [750]}}
    candidate = {"width_nm": 12.0, "gap_nm": 4.0, "length_um": 1.0}

    output = backend.run(model_profile=profile, problem_spec=problem, candidate=candidate, run_id="run_1")
    series = output["data_by_lam"]["750"]
    assert series["param_nm"][0] == 1.0
    assert series["param_nm"][-1] == 12.0


def test_mock_backend_source_has_no_builtin_hash() -> None:
    source = __import__("pathlib").Path("src/em_design_mcp/backends/mock_backend.py").read_text(encoding="utf-8")
    assert "hash(" not in source
    assert "l_min_nm" not in source
    assert "l_max_nm" not in source
