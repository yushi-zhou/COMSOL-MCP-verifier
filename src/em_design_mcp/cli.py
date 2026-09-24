from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .registries.model_profile_registry import ModelProfileRegistry
from .registries.package_registry import PackageRegistry
from .registries.problem_spec_registry import ProblemSpecRegistry
from .registries.verifier_registry import VerifierRegistry
from .tools.candidate_tools import (
    estimate_candidate_cost_payload,
    evaluate_candidate_payload,
    get_contract_bundle_payload,
    validate_candidate_payload,
)
from .utils.dotenv import load_project_dotenv
from .validation.schema_validation import deep_merge_schema


SCHEMA_VERSION = "em_design_mcp_cli_v1"
SUPPORTED_TOOLS = {
    "get_contract_bundle",
    "get_candidate_schema",
    "validate_candidate",
    "estimate_candidate_cost",
    "evaluate_candidate",
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "run-json":
        return _run_json(args)
    return _write_failure(args.output, None, [f"Unknown command: {args.command}"])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m em_design_mcp.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_json = subparsers.add_parser("run-json", help="Run one stable JSON CLI request.")
    run_json.add_argument("--input", required=True, help="Input JSON file path.")
    run_json.add_argument("--output", required=True, help="Output JSON file path.")
    run_json.add_argument("--dotenv", help="Optional dotenv file path to load before resolving registries/backend env.")
    run_json.add_argument("--pretty", action="store_true", help="Write indented output JSON.")
    return parser.parse_args(argv)


def _run_json(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    tool: str | None = None
    try:
        load_project_dotenv(args.dotenv)
        request = _read_input(Path(args.input))
        tool = str(request.get("tool") or "").strip() or None
        tool = _require_tool(request)
        result = _dispatch_tool(tool, request)
        envelope = _envelope(tool=tool, ok=True, result=result, errors=[], warnings=_result_warnings(result))
        _write_json(output_path, envelope, pretty=bool(args.pretty))
        return 0
    except _CliError as exc:
        return _write_failure(output_path, tool, [str(exc)], pretty=bool(args.pretty))
    except Exception as exc:  # Keep the CLI boundary stable even for infrastructure surprises.
        return _write_failure(output_path, tool, [f"Unhandled CLI error: {exc}"], pretty=bool(args.pretty))


def _read_input(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=_reject_nonfinite_json_constant,
        )
    except FileNotFoundError as exc:
        raise _CliError(f"Input JSON file was not found: {path}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise _CliError(f"Input JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise _CliError("Input JSON must decode to an object.")
    return payload


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite numeric constant {value!r} is not allowed")


def _require_tool(request: dict[str, Any]) -> str:
    tool = str(request.get("tool") or "").strip()
    if not tool:
        raise _CliError("Missing required top-level field: tool")
    if tool not in SUPPORTED_TOOLS:
        supported = ", ".join(sorted(SUPPORTED_TOOLS))
        raise _CliError(f"Unknown tool {tool!r}; supported tools: {supported}")
    return tool


def _dispatch_tool(tool: str, request: dict[str, Any]) -> dict[str, Any]:
    model_profile_id = _require_string(request, "model_profile_id")
    problem_id = _require_string(request, "problem_id")

    packages = PackageRegistry()
    model_profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)

    if tool == "get_contract_bundle":
        return get_contract_bundle_payload(model_profile_id, problem_id, model_profiles, problems, verifiers)

    if tool == "get_candidate_schema":
        profile = model_profiles.as_dict(model_profile_id)
        problem = problems.as_dict(problem_id)
        return deep_merge_schema(profile["design_schema"], problem.get("candidate_schema_overrides"))

    if tool == "validate_candidate":
        candidate = _require_candidate(request)
        return validate_candidate_payload(model_profile_id, problem_id, candidate, model_profiles, problems, verifiers)

    if tool == "estimate_candidate_cost":
        candidate = _require_candidate(request)
        backend = _require_string(request, "backend")
        return estimate_candidate_cost_payload(model_profile_id, problem_id, candidate, backend, model_profiles, problems, verifiers)

    if tool == "evaluate_candidate":
        candidate = _require_candidate(request)
        backend = _require_string(request, "backend")
        return evaluate_candidate_payload(model_profile_id, problem_id, candidate, backend, model_profiles, problems, verifiers)

    raise _CliError(f"Unknown tool: {tool}")


def _require_string(request: dict[str, Any], field_name: str) -> str:
    value = request.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _CliError(f"Missing required top-level field: {field_name}")
    return value.strip()


def _require_candidate(request: dict[str, Any]) -> dict[str, Any]:
    candidate = request.get("candidate")
    if not isinstance(candidate, dict):
        raise _CliError("Missing required top-level field: candidate")
    return candidate


def _envelope(*, tool: str | None, ok: bool, result: Any, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return _sanitize_for_cli(
        {
            "schema_version": SCHEMA_VERSION,
            "tool": tool,
            "ok": ok,
            "result": result,
            "errors": errors,
            "warnings": warnings,
        }
    )


def _write_failure(output_path: Path | str, tool: str | None, errors: list[str], *, pretty: bool = False) -> int:
    envelope = _envelope(tool=tool, ok=False, result=None, errors=errors, warnings=[])
    try:
        _write_json(Path(output_path), envelope, pretty=pretty)
    except Exception as exc:
        sys.stderr.write(f"Failed to write CLI output JSON: {type(exc).__name__}\n")
    return 1


def _write_json(path: Path, payload: dict[str, Any], *, pretty: bool) -> None:
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    path.write_text(json.dumps(payload, indent=indent, sort_keys=True) + "\n", encoding="utf-8")


def _result_warnings(result: Any) -> list[str]:
    if isinstance(result, dict) and isinstance(result.get("warnings"), list):
        return [str(item) for item in result["warnings"]]
    return []


def _sanitize_for_cli(value: Any) -> Any:
    replacements = _sensitive_env_values()
    return _sanitize_value(value, replacements)


def _sanitize_value(value: Any, replacements: list[str]) -> Any:
    if isinstance(value, str):
        sanitized = value
        for replacement in replacements:
            sanitized = sanitized.replace(replacement, "<redacted>")
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_value(item, replacements) for key, item in value.items()}
    return value


def _sensitive_env_values() -> list[str]:
    sensitive_markers = ("PATH", "DIR", "EXE", "MLI", "KEY", "TOKEN", "SECRET", "PASSWORD")
    values: set[str] = set()
    for key, value in os.environ.items():
        if not value or len(value) < 4:
            continue
        if key.startswith(("EM_MCP_", "EM_DESIGN_MCP_")) or any(marker in key.upper() for marker in sensitive_markers):
            values.add(value)
    return sorted(values, key=len, reverse=True)


class _CliError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
