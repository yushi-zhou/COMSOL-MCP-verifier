from __future__ import annotations

import json
import subprocess

import pytest

from em_design_mcp.backends.base import BackendConfigurationError, BackendExecutionError
from em_design_mcp.backends.matlab_livelink_backend import MatlabLiveLinkBackend


def test_livelink_resolves_relative_model_and_automatic_run_paths(tmp_path, monkeypatch) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "model.mph").write_text("fixture", encoding="utf-8")
    runs = tmp_path / "runs"
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(runs))

    def fake_runner(command, **kwargs):
        output_path = runs / "job_test" / "output.json"
        output_path.write_text(
            json.dumps({"status": "ok", "simulation_output": {"summary_metrics": {"score": 1.0}}}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backend = MatlabLiveLinkBackend(subprocess_runner=fake_runner, matlab_executable="matlab")
    output = backend.run(
        model_profile=_profile(package),
        problem_spec={"problem_id": "problem", "independent_variables": {}, "expected_outputs": ["summary_metrics"]},
        candidate={"width": 1.0},
        run_id="job_test",
    )

    payload = json.loads((runs / "job_test" / "input.json").read_text(encoding="utf-8"))
    assert payload["model"]["mph_path"] == str(package / "model.mph")
    assert payload["model"]["output_dir"] == str(runs / "job_test" / "solver")
    assert output["summary_metrics"]["score"] == 1.0
    assert (runs / "job_test" / "matlab_stdout.log").is_file()


def test_livelink_reports_missing_relative_model(tmp_path) -> None:
    with pytest.raises(BackendConfigurationError, match="Model artifact does not exist"):
        MatlabLiveLinkBackend().run(
            model_profile=_profile(tmp_path),
            problem_spec={"problem_id": "problem"},
            candidate={"width": 1.0},
            run_id="job_missing",
        )


def test_livelink_classifies_subprocess_timeout(tmp_path, monkeypatch) -> None:
    (tmp_path / "model.mph").write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))

    def timeout_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(BackendExecutionError) as caught:
        MatlabLiveLinkBackend(subprocess_runner=timeout_runner).run(
            model_profile=_profile(tmp_path),
            problem_spec={"problem_id": "problem"},
            candidate={"width": 1.0},
            run_id="job_timeout",
        )
    assert caught.value.failure_category == "backend_timeout"


def _profile(package_root) -> dict:
    return {
        "model_profile_id": "profile",
        "_package_root": str(package_root),
        "backend": {
            "type": "matlab_livelink",
            "model_artifact": {"kind": "mph", "path": "model.mph"},
        },
        "model_bindings": {
            "parameters": {"width": {"comsol_parameter": "width", "unit": "um"}},
            "tags": {"study": "std1", "export": "plot1"},
            "outputs": {"parser": "comsol_table"},
        },
        "output_schema": {"type": "object", "required": ["summary_metrics"]},
    }
