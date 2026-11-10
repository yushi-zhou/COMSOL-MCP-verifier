from __future__ import annotations

import json
from pathlib import Path

from em_design_mcp.backends.base import BackendExecutionError
from em_design_mcp.runs.result_summary import write_result_summary
from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import evaluate_candidate_payload


def test_write_result_summary_records_final_verifier_fields_without_solver_arrays(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_1"
    path = write_result_summary(
        run_dir=run_dir,
        run_id="run_1",
        backend="matlab_livelink",
        model_profile_id="profile_1",
        problem_id="problem_1",
        candidate={"width_nm": 80},
        status="evaluated",
        overall_pass=True,
        failure_category=None,
        verifier_id="verifier_1",
        simulation_output={
            "data_by_lam": {"750": {"param_nm": [1, 2], "T": [0.8, 0.9], "phi_rad": [0.1, 0.2]}},
            "summary_metrics": {"mean_transmission": 0.85},
            "artifacts": {"table_path": "solver-output.txt"},
        },
        verifier_result={
            "overall_pass": True,
            "hard_validity": True,
            "overall_pass_relaxed": True,
            "overall_pass_nominal": True,
            "overall_pass_strict": False,
            "continuous_score": 0.75,
            "normalized_margins": {"mean_transmission": 0.1},
            "hard_constraint_margins": {},
            "agent_feedback": "Nominal pass.",
            "summary_metrics": {"mean_transmission": 0.84},
            "per_condition_results": {"750": {"pass": True, "phase_coverage": 6.3}},
        },
        contract_metadata={
            "model_profile_version": "0.1",
            "problem_version": "0.2",
            "verifier_version": "0.3",
            "contract_hash": "abc123",
            "contract_hash_algorithm": "sha256",
        },
        timestamp="2026-05-27T00:00:00+00:00",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_1"
    assert payload["backend"] == "matlab_livelink"
    assert payload["candidate"] == {"width_nm": 80}
    assert payload["overall_pass"] is True
    assert payload["failure_category"] is None
    assert payload["verifier_id"] == "verifier_1"
    assert payload["summary_metrics"] == {"mean_transmission": 0.84}
    assert payload["contract"]["contract_hash"] == "abc123"
    assert payload["contract"]["model_profile_version"] == "0.1"
    assert payload["artifacts"] == {"table_path": "solver-output.txt"}
    assert payload["simulation_output_summary"] == {
        "wavelengths_present": ["750"],
        "sweep_points_by_wavelength": {"750": 2},
    }
    assert payload["verifier_result"]["per_condition_results"]["750"]["pass"] is True
    assert payload["verifier_result"]["overall_pass_nominal"] is True
    assert payload["verifier_result"]["continuous_score"] == 0.75
    assert "data_by_lam" not in payload


def test_mock_backend_writes_summary_when_runs_dir_env_is_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path))
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()
    candidate = {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}

    result = evaluate_candidate_payload("generic_mock_profile", "generic_mock_problem", candidate, "mock", model_profiles, problems, verifiers)

    summary_path = tmp_path / result["run_id"] / "result_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["backend"] == "mock"
    assert payload["overall_pass"] is True
    assert payload["verifier_id"] == "mock_generic_verifier"
    assert payload["status"] == "evaluated"
    assert payload["contract"]["model_profile_version"] == "1.0"
    assert payload["contract"]["problem_version"] == "1.0"
    assert payload["contract"]["verifier_version"] == "0.1"
    assert len(payload["contract"]["contract_hash"]) == 64


def test_backend_failure_writes_final_result_summary(tmp_path: Path, monkeypatch) -> None:
    class FailingBackend:
        warnings: list[str] = []

        def run(self, **kwargs):
            raise BackendExecutionError(
                "Failed to connect to COMSOL server.",
                failure_category="backend_connection_error",
            )

    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "em_design_mcp.tools.candidate_tools.create_backend",
        lambda *args, **kwargs: FailingBackend(),
    )
    model_profiles = ModelProfileRegistry()
    problems = ProblemSpecRegistry()
    verifiers = VerifierRegistry()
    candidate = {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}

    # The backend must match the profile's declared type, so exercise the
    # failure path through the mock profile's own backend.
    result = evaluate_candidate_payload(
        "generic_mock_profile",
        "generic_mock_problem",
        candidate,
        "mock",
        model_profiles,
        problems,
        verifiers,
    )

    summary_path = tmp_path / result["run_id"] / "result_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert result["status"] == "backend_failed"
    assert payload["status"] == "backend_failed"
    assert payload["failure_category"] == "backend_connection_error"
    assert payload["errors"] == ["Failed to connect to COMSOL server."]
    assert payload["contract"]["verifier_version"] == "0.1"
    assert len(payload["contract"]["contract_hash"]) == 64
