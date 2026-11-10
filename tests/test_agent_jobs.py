from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from em_design_mcp import worker
from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.runs.job_store import JobStore, _write_json, finalize_job, update_state
from em_design_mcp.server import create_server
from em_design_mcp.utils.file_lock import comsol_execution_slot


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


def _running_job(root: Path, job_id: str = "job_fake_running") -> Path:
    job_dir = root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "state.json").write_text(
        json.dumps({"job_id": job_id, "status": "running", "revision": 1, "updated_at": "x"}), encoding="utf-8")
    return job_dir


def test_terminal_states_are_final(tmp_path) -> None:
    state_path = _running_job(tmp_path) / "state.json"
    assert update_state(state_path, status="evaluated")["revision"] == 2
    late = update_state(state_path, status="worker_failed", message="late failure")
    assert (late["status"], late["revision"]) == ("evaluated", 2)


def test_cancelled_job_keeps_late_result_as_evidence_only(tmp_path) -> None:
    job_dir = _running_job(tmp_path)
    update_state(job_dir / "state.json", status="cancelled")
    finalize_job(job_dir / "state.json", job_dir / "result.json", {"status": "evaluated", "overall_pass": True})
    assert not (job_dir / "result.json").exists()
    assert json.loads((job_dir / "late_result.json").read_text())["overall_pass"] is True
    assert json.loads((job_dir / "state.json").read_text())["status"] == "cancelled"


@pytest.mark.parametrize("result", [{"overall_pass": True}, {"status": "cancelled"}, {"status": "made_up"}])
def test_result_without_valid_terminal_status_is_a_worker_failure(tmp_path, result) -> None:
    job_dir = _running_job(tmp_path)
    state = finalize_job(job_dir / "state.json", job_dir / "result.json", result)
    assert state["status"] == "worker_failed"
    assert not (job_dir / "result.json").exists()
    assert (job_dir / "invalid_result.json").is_file()


def test_state_write_survives_a_reader_holding_the_file(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    _write_json(state_path, {"revision": 1})
    handle = state_path.open("r", encoding="utf-8")
    threading.Timer(0.3, handle.close).start()
    _write_json(state_path, {"revision": 2})
    handle.close()
    assert json.loads(state_path.read_text())["revision"] == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_jobs_sharing_a_comsol_server_are_queued(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMSOL_SERVER_PORT", f"test{uuid.uuid4().hex[:8]}")
    state_path = _running_job(tmp_path) / "state.json"
    entered = threading.Event()

    def second_job() -> None:
        with worker._solver_slot({"backend": "matlab_livelink"}, state_path):
            entered.set()

    with comsol_execution_slot():
        thread = threading.Thread(target=second_job)
        thread.start()
        deadline = time.monotonic() + 5
        while json.loads(state_path.read_text())["status"] != "queued" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert json.loads(state_path.read_text())["status"] == "queued"
        assert not entered.is_set()
    thread.join(timeout=10)
    assert entered.is_set()
    assert json.loads(state_path.read_text())["status"] == "running"


def test_cancel_records_first_and_terminates_the_process_tree(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path))
    job_dir = _running_job(tmp_path)
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **options)
    try:
        (job_dir / "pid.json").write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
        packages = PackageRegistry()
        cancelled = JobStore(packages, ModelProfileRegistry(packages=packages)).cancel("job_fake_running")
        assert cancelled["status"] == "cancelled" and cancelled["terminal"] is True
        assert cancelled["termination_signalled"] is True
        assert process.wait(timeout=10) is not None
    finally:
        if process.poll() is None:
            process.kill()


def test_long_poll_does_not_block_other_tools(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path))
    _running_job(tmp_path)
    tools = create_server()._tool_manager._tools

    async def scenario():
        async def poll():
            started = time.monotonic()
            await tools["get_run"].fn("job_fake_running", after_revision=1, wait_seconds=2)
            return time.monotonic() - started

        async def discover():
            await asyncio.sleep(0.2)
            started = time.monotonic()
            await tools["discover_designs"].fn("")
            return time.monotonic() - started

        return await asyncio.gather(poll(), discover())

    poll_seconds, discover_seconds = asyncio.run(scenario())
    assert poll_seconds >= 1.5
    assert discover_seconds < 1.0
