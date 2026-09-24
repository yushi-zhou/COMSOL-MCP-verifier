from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from em_design_mcp.runs.result_summary import write_result_summary


def test_show_last_run_handles_missing_runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    script = _load_show_last_run()
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "missing"))

    assert script.main() == 0

    captured = capsys.readouterr()
    assert "No run summaries found" in captured.out


def test_show_last_run_prints_latest_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    script = _load_show_last_run()
    runs_dir = tmp_path / "runs"
    write_result_summary(
        run_dir=runs_dir / "run_1",
        run_id="run_1",
        backend="matlab_livelink",
        model_profile_id="profile_1",
        problem_id="problem_1",
        candidate={"width_nm": 80},
        status="evaluated",
        overall_pass=False,
        failure_category="phase_limited",
        verifier_id="verifier_1",
        simulation_output={
            "summary_metrics": {"mean_transmission": 0.85},
            "artifacts": {"table_path": "solver-output.txt"},
        },
        verifier_result={
            "per_condition_results": {
                "750": {
                    "pass": False,
                    "phase_coverage": 3.1,
                }
            }
        },
        timestamp="2026-05-27T00:00:00+00:00",
    )
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(runs_dir))

    assert script.main() == 0

    captured = capsys.readouterr()
    assert "Run ID: run_1" in captured.out
    assert "Backend: matlab_livelink" in captured.out
    assert "Model profile: profile_1" in captured.out
    assert "Problem: problem_1" in captured.out
    assert "Overall pass: False" in captured.out
    assert "Failure category: phase_limited" in captured.out
    assert "Verifier: verifier_1" in captured.out
    assert "width_nm: 80" in captured.out
    assert "mean_transmission: 0.85" in captured.out
    assert "750:" in captured.out
    assert "phase_coverage: 3.1" in captured.out
    assert "table_path: solver-output.txt" in captured.out


def _load_show_last_run():
    path = Path(__file__).resolve().parents[1] / "scripts" / "show_last_run.py"
    spec = importlib.util.spec_from_file_location("show_last_run_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
