from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.runs.job_store import JobStore, update_state


def test_persistent_worker_returns_compact_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))
    packages = PackageRegistry()
    profiles = ModelProfileRegistry(packages=packages)
    jobs = JobStore(packages, profiles)

    started = jobs.start(
        model_profile_id="generic_mock_profile",
        problem_id="generic_mock_problem",
        candidate={"width_nm": 80, "gap_nm": 10, "length_um": 2.5},
        backend="mock",
        wait_seconds=10,
    )

    assert started["terminal"] is True
    assert started["status"] in {"evaluated", "verifier_failed"}
    assert started["revision"] >= 2
    assert started["summary_metrics"]
    assert "verifier_feedback" in started
    assert "result" not in started

    full = jobs.get(started["job_id"], include_result=True)
    assert full["result"]["candidate"]["width_nm"] == 80


def test_cancelled_state_cannot_be_overwritten_by_late_worker(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"job_id": "job_test", "status": "cancelled", "revision": 3}),
        encoding="utf-8",
    )
    state = update_state(state_path, status="evaluated")
    assert state["status"] == "cancelled"
    assert state["revision"] == 3


def test_worker_preserves_relative_package_and_run_roots(monkeypatch, tmp_path) -> None:
    shutil.copytree(Path(__file__).parent / "fixtures" / "designs", tmp_path / "models")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EM_DESIGN_PACKAGE_ROOTS", "models")
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", "runs")
    packages = PackageRegistry()
    jobs = JobStore(packages, ModelProfileRegistry(packages=packages))

    started = jobs.start(
        model_profile_id="generic_mock_profile", problem_id="generic_mock_problem",
        candidate={"width_nm": 80, "gap_nm": 10, "length_um": 2.5}, backend="mock", wait_seconds=10,
    )

    assert started["terminal"] is True, started
    assert started["status"] in {"evaluated", "verifier_failed"}, started
    run_dir = tmp_path / "runs" / started["job_id"]
    assert Path(started["run_dir"]) == run_dir
    result = json.loads((run_dir / "result.json").read_text())
    assert result["candidate"]["width_nm"] == 80
    assert (run_dir / "provenance.json").is_file()
    assert os.environ["EM_DESIGN_PACKAGE_ROOTS"] == "models"
    assert os.environ["EM_DESIGN_MCP_RUNS_DIR"] == "runs"


@pytest.mark.parametrize("action", ["evaluate", "inspect"])
def test_worker_uses_explicit_registry_roots_without_changing_parent_env(monkeypatch, tmp_path, action) -> None:
    package_root = tmp_path / "models"
    shutil.copytree(Path(__file__).parent / "fixtures" / "designs", package_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EM_DESIGN_PACKAGE_ROOTS", "unrelated-models")
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", "")
    packages = PackageRegistry(roots=["models"])
    jobs = JobStore(packages, ModelProfileRegistry(packages=packages))

    if action == "evaluate":
        started = jobs.start(
            model_profile_id="generic_mock_profile", problem_id="generic_mock_problem",
            candidate={"width_nm": 80, "gap_nm": 10, "length_um": 2.5}, backend="mock", wait_seconds=10,
        )
        assert started["status"] in {"evaluated", "verifier_failed"}, started
    else:
        # This COMSOL-free profile must reach the inspection boundary in the
        # actual worker, rather than fail to discover its explicitly chosen root.
        started = jobs.start_inspection(model_profile_id="generic_mock_profile", topics=["studies"], wait_seconds=10)
        assert started["status"] == "backend_failed", started
        assert started["failure_category"] == "inspection_unsupported", started

    assert started["terminal"] is True, started
    run_dir = package_root / "runs" / started["job_id"]
    assert Path(started["run_dir"]) == run_dir
    assert (run_dir / "result.json").is_file()
    assert os.environ["EM_DESIGN_PACKAGE_ROOTS"] == "unrelated-models"
    assert os.environ["EM_DESIGN_MCP_RUNS_DIR"] == ""
