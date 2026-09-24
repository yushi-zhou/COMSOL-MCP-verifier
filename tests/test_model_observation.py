import json
import subprocess

import pytest

from em_design_mcp.backends.base import BackendExecutionError
from em_design_mcp.backends.matlab_livelink_backend import MatlabLiveLinkBackend
from em_design_mcp.schemas.model_observation import Measurement, selected_measurements, validate_topics
from em_design_mcp.tools.model_tools import compact, compact_inspection
from em_design_mcp.validation.physics_preflight import dataset_binding, run_preflight


def facts():
    return {
        "schema_version": "em_model_facts_v1",
        "studies": {
            "studies": [{"id": "study_a"}, {"id": "study_b"}],
            "solutions": [{"tag": "sol_a", "study": "study_a", "empty": False},
                          {"tag": "sol_b", "study": "study_b", "empty": False}],
            "datasets": [{"tag": "data_a", "solution": "sol_a"},
                         {"tag": "data_b", "solution": "sol_b"},
                         {"tag": "cut_a", "source": "data_a"}],
        },
        "excitation": [{"id": "comp/wave/in", "active": True, "effective_active": True,
                        "properties": {"InputType": "H", "H0": ["0", "1", "0"]}}],
        "physics": [{"id": "comp/wave", "active": True}],
        "selections": [{"id": "comp/body", "component": "comp", "geometry": "geom", "dimension": 3, "entities": [1, 2], "count": 2}],
        "materials": [{"id": "comp/mat", "component": "comp", "active": True,
                       "selection": {"geometry": "geom", "dimension": 3, "entities": [2, 1]}}],
        "mesh": [{"id": "comp/mesh", "stats": {"numelem": 100}}],
    }


def measurement(**overrides):
    return {"id": "power", "expression": "P", "method": "global", "unit": "W",
            "study": "study_a", "solution": "sol_a", "dataset": "data_a", **overrides}


def test_dataset_binding_resolves_derived_and_multiphysics_sources():
    assert dataset_binding(facts(), "cut_a", "sol_a", "study_a")["tag"] == "sol_a"
    assert dataset_binding(facts(), "data_b", "sol_b", "study_b")["tag"] == "sol_b"
    with pytest.raises(ValueError, match="expected"):
        dataset_binding(facts(), "data_b", "sol_a", "study_a")
    with pytest.raises(ValueError, match="study"):
        dataset_binding(facts(), "data_a", "sol_a", "study_b")


@pytest.mark.parametrize("change", ["empty", "unknown", "cycle", "ambiguous"])
def test_unverified_dataset_fails(change):
    observed = facts()
    tree = observed["studies"]
    if change in {"empty", "unknown"}:
        tree["solutions"][0]["empty"] = True if change == "empty" else None
    elif change == "cycle":
        tree["datasets"][0] = {"tag": "data_a", "source": "cut_a"}
    else:
        tree["datasets"][0]["properties"] = {"data1": "data_a", "data2": "data_b"}
    with pytest.raises(ValueError):
        dataset_binding(observed, "data_a", "sol_a", "study_a")


def test_preflight_requires_effective_excitation_and_exact_observed_properties():
    check = {"id": "drive", "kind": "excitation", "target": "comp/wave/in",
             "expected": {"InputType": "H", "H0": ["0", "1", "0"]}}
    observed = facts()
    assert run_preflight(observed, [check])["valid"]
    observed["excitation"][0]["effective_active"] = False
    assert not run_preflight(observed, [check])["valid"]
    observed["excitation"][0]["effective_active"] = True
    del observed["excitation"][0]["properties"]["H0"]
    assert "unavailable" in run_preflight(observed, [check])["checks"][0]["message"]


def test_material_check_does_not_confuse_boundary_and_domain_entity_numbers():
    check = {"id": "material", "kind": "material_selection", "target": "comp/mat", "selection": "comp/body"}
    observed = facts()
    assert run_preflight(observed, [check])["valid"]
    observed["materials"][0]["selection"]["dimension"] = 2
    assert not run_preflight(observed, [check])["valid"]


def test_preflight_checks_evaluated_angle_not_only_parameter_name():
    observed = facts()
    node = observed["excitation"][0]
    node["properties"]["alpha1_inc"] = "theta"
    node["evaluated_properties"] = {"alpha1_inc": {"status": "ok", "value_real": 0.5, "value_imag": 0, "unit": "rad"}}
    check = {"id": "angle", "kind": "excitation", "target": "comp/wave/in",
             "expected": {"alpha1_inc": "theta"}, "expected_values": {"alpha1_inc": {"value": 0.5, "unit": "rad", "atol": 1e-12}}}
    assert run_preflight(observed, [check])["valid"]
    node["evaluated_properties"]["alpha1_inc"]["value_real"] = 0.1
    assert not run_preflight(observed, [check])["valid"]


def test_material_selection_ids_are_local_to_component_and_geometry():
    check = {"id": "material", "kind": "material_selection", "target": "comp/mat", "selection": "comp/body"}
    observed = facts()
    observed["selections"][0]["geometry"] = "other_geom"
    assert not run_preflight(observed, [check])["valid"]
    observed["selections"][0]["geometry"] = "geom"
    observed["selections"][0]["component"] = "other_comp"
    assert not run_preflight(observed, [check])["valid"]


def test_unknown_check_or_unknown_mesh_is_failure():
    assert not run_preflight(facts(), [{"id": "guess", "kind": "arbitrary_rule", "target": "anything"}])["valid"]
    observed = facts()
    observed["mesh"][0]["stats"] = {}
    assert not run_preflight(observed, [{"id": "mesh", "kind": "mesh_present", "target": "comp/mesh"}])["valid"]
    assert run_preflight({}, [])["status"] == "not_configured"


@pytest.mark.parametrize("override", [
    {"method": "integrate"}, {"selection": "body"}, {"solnum": 0}, {"solnum": True},
    {"outersolnum": "auto"}, {"unit": ""}, {"raw_matlab": "disp(1)"},
])
def test_unsafe_or_incomplete_measurement_definitions_rejected(override):
    with pytest.raises(ValueError):
        Measurement.model_validate(measurement(**override))


def test_measurements_bind_each_physics_dataset_and_reject_unknown_names():
    profile = {"measurements": [measurement(), measurement(id="temperature", expression="T", unit="K",
               study="study_b", solution="sol_b", dataset="data_b", method="maximum", selection="body", dimension="volume")]}
    entries = selected_measurements(profile)
    assert [x["dataset"] for x in entries] == ["data_a", "data_b"]
    assert selected_measurements(profile, []) == []
    with pytest.raises(ValueError, match="Unknown"):
        selected_measurements(profile, ["arbitrary_expression"])
    with pytest.raises(ValueError, match="Duplicate"):
        selected_measurements({"measurements": [measurement(), measurement()]})
    with pytest.raises(ValueError, match="Unsupported"):
        validate_topics(["raw_tree"])


def test_backend_selective_inspection_does_not_apply_candidate_or_solve(tmp_path, monkeypatch):
    (tmp_path / "model.mph").write_bytes(b"opaque model")
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))
    profile = {"backend": {"type": "matlab_livelink", "model_artifact": {"path": str(tmp_path / "model.mph")}},
               "measurements": [measurement()]}

    def runner(command, **kwargs):
        folder = tmp_path / "runs" / "job_read"
        payload = json.loads((folder / "input.json").read_text())
        assert payload["mode"] == "inspect" and not payload["apply_candidate"]
        assert set(payload["topics"]) == {"studies", "selections", "excitation"}
        assert payload["measurements"][0]["dataset"] == "data_a"
        (folder / "output.json").write_text(json.dumps({"status": "ok", "model_facts": facts(),
            "measurements": [{"id": "power", "value_real": 2, "value_imag": 1, "unit": "W"}]}))
        return subprocess.CompletedProcess(command, 0)

    output = MatlabLiveLinkBackend(subprocess_runner=runner).inspect(model_profile=profile, problem_spec={},
        run_id="job_read", topics=["excitation"], measurement_ids=["power"])
    assert output["measurements"][0]["value_imag"] == 1


def test_preflight_blocks_solver_launch_with_observed_evidence(tmp_path, monkeypatch):
    (tmp_path / "model.mph").write_bytes(b"opaque model")
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))
    profile = {"backend": {"type": "matlab_livelink", "model_artifact": {"path": str(tmp_path / "model.mph")}},
        "preflight": [{"id": "active", "kind": "physics_active", "target": "comp/missing"}]}
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        folder = tmp_path / "runs" / "job_blocked" / "preflight"
        payload = json.loads((folder / "input.json").read_text())
        assert payload["mode"] == "inspect" and payload["apply_candidate"]
        (folder / "output.json").write_text(json.dumps({"status": "ok", "model_facts": facts()}))
        return subprocess.CompletedProcess(command, 0)

    with pytest.raises(BackendExecutionError) as error:
        MatlabLiveLinkBackend(subprocess_runner=runner).run(model_profile=profile, problem_spec={}, candidate={}, run_id="job_blocked")
    assert error.value.failure_category == "physics_preflight_failed"
    assert len(calls) == 1


def test_compact_output_bounds_arrays_and_reports_omissions():
    full = {"spectra": list(range(10000)), "log": "x" * 10000}
    brief = compact(full)
    assert brief["spectra"][-1] == {"omitted": 9988, "total": 10000}
    assert len(json.dumps(brief)) < 1000
    assert len(full["spectra"]) == 10000
    assert compact("wave", depth=8) == "wave"


def test_compact_inspection_prioritizes_actual_driven_port():
    passive = [{"id": str(i), "effective_active": False, "properties": {}} for i in range(30)]
    driven = {"id": "driven", "effective_active": True, "properties": {"PortExcitation": "on"}}
    result = {"facts": {"excitation": passive + [driven]}}
    brief = compact_inspection(result)
    assert brief["facts"]["excitation"][0]["id"] == "driven"
    assert brief["fact_counts"]["excitation"] == 31
    assert result["facts"]["excitation"][0]["id"] == "0"
