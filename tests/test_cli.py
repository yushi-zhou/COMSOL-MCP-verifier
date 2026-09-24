from __future__ import annotations

import json
from pathlib import Path

from em_design_mcp.cli import SCHEMA_VERSION, main


def test_cli_run_json_get_candidate_schema(tmp_path: Path, monkeypatch) -> None:
    output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "get_candidate_schema",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
        },
    )

    assert output["schema_version"] == SCHEMA_VERSION
    assert output["tool"] == "get_candidate_schema"
    assert output["ok"] is True
    assert output["errors"] == []
    assert output["warnings"] == []
    assert output["result"]["required"] == ["width_nm", "gap_nm", "length_um"]


def test_cli_run_json_get_contract_bundle_matches_candidate_schema(tmp_path: Path, monkeypatch) -> None:
    bundle_output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "get_contract_bundle",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
        },
    )
    schema_output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "get_candidate_schema",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
        },
    )

    bundle = bundle_output["result"]
    assert bundle_output["schema_version"] == SCHEMA_VERSION
    assert bundle_output["tool"] == "get_contract_bundle"
    assert bundle_output["ok"] is True
    assert bundle["problem_summary"]["problem_id"] == "generic_mock_problem"
    assert bundle["profile_summary"]["model_profile_id"] == "generic_mock_profile"
    assert bundle["effective_candidate_schema"] == schema_output["result"]
    assert bundle["thresholds"] == {"score": 1.0}
    assert bundle["expected_outputs"] == ["summary_metrics"]
    assert bundle["verifier_summary"]["required_outputs"] == ["summary_metrics"]


def test_cli_run_json_validate_candidate(tmp_path: Path, monkeypatch) -> None:
    output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "validate_candidate",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
            "candidate": _candidate(),
        },
    )

    assert _envelope_keys(output)
    assert output["tool"] == "validate_candidate"
    assert output["ok"] is True
    assert output["result"]["valid"] is True
    assert output["result"]["errors"] == []


def test_cli_run_json_estimate_candidate_cost(tmp_path: Path, monkeypatch) -> None:
    output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "estimate_candidate_cost",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
            "candidate": _candidate(),
            "backend": "mock",
        },
    )

    assert _envelope_keys(output)
    assert output["tool"] == "estimate_candidate_cost"
    assert output["ok"] is True
    assert output["result"]["valid"] is True
    assert output["result"]["estimated_sweep_points"] == 0


def test_cli_run_json_evaluate_candidate_with_mock_backend(tmp_path: Path, monkeypatch) -> None:
    output = _run_cli(
        tmp_path,
        monkeypatch,
        {
            "tool": "evaluate_candidate",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
            "candidate": _candidate(),
            "backend": "mock",
        },
    )

    assert _envelope_keys(output)
    assert output["tool"] == "evaluate_candidate"
    assert output["ok"] is True
    assert output["result"]["backend"] == "mock"
    assert output["result"]["status"] in {"evaluated", "verifier_failed"}
    assert "summary_metrics" in output["result"]["simulation_output"]


def test_cli_run_json_unknown_tool_returns_cli_failure(tmp_path: Path, monkeypatch) -> None:
    output, exit_code = _run_cli_with_exit_code(
        tmp_path,
        monkeypatch,
        {
            "tool": "raw_comsol_command",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
        },
    )

    assert exit_code == 1
    assert _envelope_keys(output)
    assert output["tool"] == "raw_comsol_command"
    assert output["ok"] is False
    assert output["result"] is None
    assert any("Unknown tool" in error for error in output["errors"])
    assert output["warnings"] == []


def test_cli_run_json_missing_required_field_returns_cli_failure(tmp_path: Path, monkeypatch) -> None:
    output, exit_code = _run_cli_with_exit_code(
        tmp_path,
        monkeypatch,
        {
            "tool": "estimate_candidate_cost",
            "model_profile_id": "generic_mock_profile",
            "problem_id": "generic_mock_problem",
            "candidate": _candidate(),
        },
    )

    assert exit_code == 1
    assert output["ok"] is False
    assert output["result"] is None
    assert any("backend" in error for error in output["errors"])


def test_cli_run_json_accepts_utf8_bom_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EM_DESIGN_MCP_RUNS_DIR", raising=False)
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "tool": "validate_candidate",
                "model_profile_id": "generic_mock_profile",
                "problem_id": "generic_mock_problem",
                "candidate": _candidate(),
            }
        ),
        encoding="utf-8-sig",
    )

    exit_code = main(
        [
            "run-json",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--dotenv",
            str(tmp_path / "missing.env"),
        ]
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output["ok"] is True
    assert output["result"]["valid"] is True


def test_cli_run_json_rejects_nonfinite_json_numbers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EM_DESIGN_MCP_RUNS_DIR", raising=False)
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        """
        {
          "tool": "validate_candidate",
          "model_profile_id": "generic_mock_profile",
          "problem_id": "generic_mock_problem",
          "candidate": {"width_nm": NaN, "gap_nm": 10, "length_um": 2.5}
        }
        """,
        encoding="utf-8",
    )

    exit_code = main(
        [
            "run-json",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--dotenv",
            str(tmp_path / "missing.env"),
        ]
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert output["ok"] is False
    assert any("non-finite numeric constant" in error for error in output["errors"])


def _run_cli(tmp_path: Path, monkeypatch, payload: dict) -> dict:
    output, exit_code = _run_cli_with_exit_code(tmp_path, monkeypatch, payload)
    assert exit_code == 0
    return output


def _run_cli_with_exit_code(tmp_path: Path, monkeypatch, payload: dict) -> tuple[dict, int]:
    monkeypatch.delenv("EM_DESIGN_MCP_RUNS_DIR", raising=False)
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "run-json",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--dotenv",
            str(tmp_path / "missing.env"),
            "--pretty",
        ]
    )

    assert output_path.exists()
    return json.loads(output_path.read_text(encoding="utf-8")), exit_code


def _candidate() -> dict:
    return {
        "width_nm": 80,
        "gap_nm": 10,
        "length_um": 2.5,
    }


def _envelope_keys(output: dict) -> bool:
    return set(output) == {"schema_version", "tool", "ok", "result", "errors", "warnings"}
