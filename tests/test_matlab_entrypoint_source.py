from __future__ import annotations

from pathlib import Path


def test_matlab_entrypoint_uses_generic_values_from_dotted_path_resolver() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")

    assert "function [found, value] = resolve_dotted_path" in text
    assert "strcmp(values_from, 'problem_spec.independent_variables.wavelength_nm')" not in text
    assert "Unsupported sweep values_from binding" not in text
    assert "format_comsol_value(numeric_value, unit)" in text


def test_matlab_entrypoint_leaves_table_parsing_to_python_backend() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")
    runtime_body = text.split("function apply_parameter_bindings", maxsplit=1)[0]

    assert "parse_spectral_response_table(" not in runtime_body
    assert "parse_comsol_table(" not in runtime_body
    assert "simulation_output.spectral_response" not in runtime_body
    assert "simulation_output.data_by_lam" not in runtime_body
    assert "simulation_output.summary_metrics = struct();" in runtime_body
    assert "simulation_output.artifacts = struct('table_path', table_path, 'input_json_path', char(input_json_path));" in runtime_body


def test_matlab_entrypoint_can_save_successful_solved_model() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")
    runtime_body = text.split("function apply_parameter_bindings", maxsplit=1)[0]

    assert "get_optional(outputs, 'save_solved_model', false)" in runtime_body
    assert "solved_model_path = fullfile(output_dir, [char(request.run_id) '.mph']);" in runtime_body
    assert "mphsave(model, solved_model_path);" in runtime_body
    assert "simulation_output.artifacts.solved_model_path = solved_model_path;" in runtime_body


def test_matlab_entrypoint_can_select_all_outer_solutions_for_evaluation() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")
    runtime_body = text.split("function apply_parameter_bindings", maxsplit=1)[0]

    assert "get_optional(tags, 'eval_outerinput', '')" in runtime_body
    assert ".set('outerinput', char(eval_outerinput));" in runtime_body


def test_matlab_entrypoint_handles_profile_declared_feature_switches() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")

    assert "apply_shape_switch(model, candidate, bindings);" in text
    assert "function apply_shape_switch" in text
    assert "apply_feature_switches(model, candidate, bindings);" in text
    assert "function apply_feature_switches" in text
    assert "feature_switches = get_optional(bindings, 'feature_switches', []);" in text
    assert "candidate_field = require_binding(feature_switch, 'candidate_field');" in text
    assert "path = require_binding(feature_binding, 'path');" in text
    assert "component_tag = require_binding(path, 'component');" in text
    assert "physics_tag = require_binding(path, 'physics');" in text
    assert "parent_feature_tag = require_binding(path, 'parent_feature');" in text
    assert "feature_tag = require_binding(path, 'feature');" in text
    assert ".active(active_state);" in text


def test_matlab_entrypoint_classifies_infrastructure_failures_separately() -> None:
    text = (Path(__file__).resolve().parents[1] / "matlab" / "run_em_design_from_json.m").read_text(encoding="utf-8")

    assert "category = 'backend_connection_error';" in text
    assert "category = 'backend_license_error';" in text
    assert "category = 'backend_timeout';" in text
    assert "category = 'backend_execution_error';" in text
