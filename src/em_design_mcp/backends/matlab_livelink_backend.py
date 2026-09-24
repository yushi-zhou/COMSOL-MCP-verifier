from __future__ import annotations

import copy
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from ..execution_policy import resolve_execution_policy
from ..parsers.comsol_table_parser import DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM, parse_comsol_table_file
from ..registries.plugin_registry import PluginRegistry
from ..runs.result_summary import write_result_summary
from ..utils.contract_metadata import build_contract_metadata
from ..utils.paths import configured_run_root, project_path, resolve_package_path
from ..schemas.model_observation import selected_measurements, validate_topics
from ..validation.physics_preflight import check_topics, run_preflight
from .base import BackendConfigurationError, BackendExecutionError


DEFAULT_MATLAB_EXECUTABLE_ENV = "MATLAB_EXE"
DEFAULT_COMSOL_MLI_ENV = "COMSOL_MLI"


class MatlabLiveLinkBackend:
    def __init__(
        self,
        *,
        subprocess_runner: Callable[..., Any] | None = None,
        matlab_executable: str | None = None,
        timeout_seconds: int = 3600,
        parser_registry: PluginRegistry | None = None,
    ) -> None:
        self._subprocess_runner = subprocess_runner or subprocess.run
        self._matlab_executable = matlab_executable
        self._timeout_seconds = timeout_seconds
        self._parser_registry = parser_registry or PluginRegistry()
        self.warnings: list[str] = []

    def run(
        self,
        *,
        model_profile: dict[str, Any],
        problem_spec: dict[str, Any],
        candidate: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        self.warnings = []
        active_profile = {**model_profile, "_active_run_id": run_id}
        config = self._resolve_config(active_profile)
        timeout_seconds = self._resolve_timeout_seconds(model_profile, problem_spec)
        run_dir = configured_run_root(model_profile) / run_id
        _ensure_directory(run_dir, "run directory")

        input_json_path = run_dir / "input.json"
        output_json_path = run_dir / "output.json"
        payload = self._build_input_payload(
            model_profile=model_profile,
            problem_spec=problem_spec,
            candidate=candidate,
            run_id=run_id,
            config=config,
        )
        checks = list(model_profile.get("preflight") or []) + list(problem_spec.get("preflight") or [])
        if checks:
            observed = self.inspect(
                model_profile=model_profile, problem_spec=problem_spec, run_id=run_id,
                topics=check_topics(checks), candidate=candidate,
                artifact_dir=run_dir / "preflight",
            )
            preflight = observed["preflight"]
            if not preflight["valid"]:
                raise BackendExecutionError(
                    "Physics preflight failed: " + "; ".join(item.get("message", "") for item in preflight["checks"] if item["status"] == "failed") + f"; evidence: {run_dir / 'preflight' / 'output.json'}",
                    failure_category="physics_preflight_failed",
                )
        else:
            preflight = run_preflight({}, [])
        input_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        self._run_matlab(config["matlab_executable"], input_json_path, output_json_path, timeout_seconds)
        output_payload = self._read_output_json(output_json_path)
        self.warnings = _as_string_list(output_payload.get("warnings"))
        simulation_output = self._simulation_output_from_payload(output_payload, problem_spec, model_profile)
        _validate_measurement_ids(simulation_output.get("measurements"), payload["measurements"])
        simulation_output["preflight"] = preflight
        write_result_summary(
            run_dir=run_dir,
            run_id=run_id,
            backend="matlab_livelink",
            model_profile_id=str(model_profile.get("model_profile_id") or ""),
            problem_id=str(problem_spec.get("problem_id") or ""),
            candidate=candidate,
            status="evaluated",
            simulation_output=simulation_output,
            contract_metadata=build_contract_metadata(model_profile, problem_spec),
        )
        return simulation_output

    def inspect(
        self, *, model_profile: dict[str, Any], problem_spec: dict[str, Any], run_id: str,
        topics: list[str] | None = None, measurement_ids: list[str] | None = None,
        source_path: str | None = None, candidate: dict | None = None,
        artifact_dir: Path | None = None,
    ) -> dict[str, Any]:
        requested = validate_topics(topics)
        checks = list(model_profile.get("preflight") or []) + list(problem_spec.get("preflight") or [])
        observed_topics = sorted(set(requested) | set(check_topics(checks)))
        measurements = selected_measurements(model_profile, measurement_ids or [])
        if measurements:
            observed_topics = sorted(set(observed_topics) | {"studies", "selections"})
        config = self._resolve_config({**model_profile, "_active_run_id": run_id})
        if source_path:
            config["mph_path"] = source_path
        run_dir = artifact_dir or configured_run_root(model_profile) / run_id
        _ensure_directory(run_dir, "inspection directory")
        payload = self._build_input_payload(model_profile=model_profile, problem_spec=problem_spec, candidate=candidate or {}, run_id=run_id, config=config)
        payload.update(mode="inspect", topics=observed_topics, measurements=measurements, apply_candidate=candidate is not None)
        input_path, output_path = run_dir / "input.json", run_dir / "output.json"
        input_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._run_matlab(config["matlab_executable"], input_path, output_path, self._resolve_timeout_seconds(model_profile, problem_spec))
        output = self._read_output_json(output_path)
        facts = output.get("model_facts")
        if not isinstance(facts, dict) or facts.get("schema_version") != "em_model_facts_v1":
            raise BackendExecutionError("Missing or unsupported actual model facts.", failure_category="inspection_failed")
        _validate_measurement_ids(output.get("measurements"), measurements)
        return {
            "model_facts": facts,
            "requested_topics": requested,
            "measurements": output.get("measurements") or [],
            "preflight": run_preflight(facts, checks),
            "facts_path": str(output_path),
        }

    def _resolve_timeout_seconds(self, model_profile: dict[str, Any], problem_spec: dict[str, Any]) -> int:
        for source in (model_profile.get("execution_policy"), problem_spec.get("execution_policy")):
            if isinstance(source, dict) and "backend_timeout_seconds" in source:
                return int(resolve_execution_policy(model_profile, problem_spec)["backend_timeout_seconds"])
        return self._timeout_seconds

    def _resolve_config(self, model_profile: dict[str, Any]) -> dict[str, Any]:
        backend = model_profile.get("backend") or {}
        if backend.get("type") != "matlab_livelink":
            raise BackendConfigurationError(
                "backend='matlab_livelink' requires a model profile whose backend.type is 'matlab_livelink'."
            )

        artifact = backend.get("model_artifact") or {}
        package_root = model_profile.get("_package_root")
        artifact_path = artifact.get("path")
        mph_path_env = artifact.get("path_env")
        if artifact_path:
            mph_path = resolve_package_path(str(artifact_path), package_root)
            if not mph_path.exists():
                raise BackendConfigurationError(f"Model artifact does not exist: {mph_path}")
        elif mph_path_env:
            mph_path = _resolve_required_path_env(str(mph_path_env), must_exist=True)
        else:
            raise BackendConfigurationError(
                "The selected model profile must declare backend.model_artifact.path or path_env."
            )

        configured_output_dir = backend.get("output_dir")
        output_dir_env = backend.get("output_dir_env")
        if configured_output_dir:
            output_dir = resolve_package_path(str(configured_output_dir), package_root)
        elif output_dir_env:
            output_dir = _resolve_required_path_env(str(output_dir_env), must_exist=False)
        else:
            output_dir = configured_run_root(model_profile) / str(model_profile.get("_active_run_id") or "solver") / "solver"
        _ensure_directory(output_dir, "solver output directory")

        matlab_executable = self._matlab_executable or _resolve_optional_env(
            backend.get("matlab_executable_env") or DEFAULT_MATLAB_EXECUTABLE_ENV,
            default="matlab",
        )
        comsol_mli_path = _resolve_optional_env(backend.get("comsol_mli_env") or DEFAULT_COMSOL_MLI_ENV)

        companion_paths = [
            str(resolve_package_path(str(value), package_root))
            for value in artifact.get("companion_paths") or []
        ]
        for env_name in artifact.get("companion_paths_env") or []:
            value = _resolve_optional_env(str(env_name))
            if value:
                companion_paths.append(value)

        return {
            "mph_path": str(mph_path),
            "output_dir": str(output_dir),
            "matlab_executable": matlab_executable,
            "comsol_mli_path": comsol_mli_path,
            "companion_paths": companion_paths,
        }

    def _build_input_payload(
        self,
        *,
        model_profile: dict[str, Any],
        problem_spec: dict[str, Any],
        candidate: dict[str, Any],
        run_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "mode": "evaluate",
            "topics": ["studies", "outputs"],
            "measurements": selected_measurements(model_profile),
            "model_profile_id": model_profile.get("model_profile_id"),
            "problem_id": problem_spec.get("problem_id"),
            "candidate": copy.deepcopy(candidate),
            "model_profile": {
                "model_profile_id": model_profile.get("model_profile_id"),
                "compatible_problem_families": copy.deepcopy(model_profile.get("compatible_problem_families") or []),
                "model_bindings": _allowed_model_bindings(model_profile.get("model_bindings") or {}),
                "output_schema": copy.deepcopy(model_profile.get("output_schema") or {}),
            },
            "problem_spec": {
                "independent_variables": copy.deepcopy(problem_spec.get("independent_variables") or {}),
                "expected_outputs": copy.deepcopy(problem_spec.get("expected_outputs") or []),
            },
            "model": {
                "mph_path": config["mph_path"],
                "output_dir": config["output_dir"],
                "companion_paths": copy.deepcopy(config.get("companion_paths") or []),
            },
            "runtime": {
                "comsol_mli_path": config.get("comsol_mli_path"),
                "comsol_server_port": int(os.environ.get("COMSOL_SERVER_PORT") or 2036),
            },
            "model_bindings": _allowed_model_bindings(model_profile.get("model_bindings") or {}),
            "output_schema": copy.deepcopy(model_profile.get("output_schema") or {}),
        }

    def _run_matlab(self, matlab_executable: str, input_json_path: Path, output_json_path: Path, timeout_seconds: int) -> None:
        entrypoint_dir = project_path("matlab")
        if not (entrypoint_dir / "run_em_design_from_json.m").exists():
            raise BackendConfigurationError("MATLAB LiveLink entrypoint is missing from the repository.")

        batch_command = (
            f"addpath({_matlab_string(str(entrypoint_dir))}); "
            f"run_em_design_from_json({_matlab_string(str(input_json_path))}, "
            f"{_matlab_string(str(output_json_path))})"
        )
        command = [matlab_executable, "-batch", batch_command]

        try:
            completed = self._subprocess_runner(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise BackendConfigurationError(f"MATLAB executable was not found: {matlab_executable}") from exc
        except subprocess.TimeoutExpired as exc:
            _write_process_logs(input_json_path.parent, exc.stdout, exc.stderr)
            raise BackendExecutionError(
                f"MATLAB LiveLink run timed out after {timeout_seconds} seconds.",
                failure_category="backend_timeout",
            ) from exc

        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        _write_process_logs(input_json_path.parent, stdout, stderr)
        returncode = int(getattr(completed, "returncode", 0))
        if returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"MATLAB exited with code {returncode}."
            raise BackendExecutionError(detail, failure_category=_classify_matlab_process_failure(detail))

    def _read_output_json(self, output_json_path: Path) -> dict[str, Any]:
        if not output_json_path.exists():
            raise BackendExecutionError(
                f"MATLAB LiveLink completed but did not write output JSON: {output_json_path}",
                failure_category="result_parse_error",
            )
        try:
            payload = json.loads(output_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BackendExecutionError(
                f"MATLAB LiveLink output JSON is invalid: {exc}",
                failure_category="result_parse_error",
            ) from exc
        if not isinstance(payload, dict):
            raise BackendExecutionError("MATLAB LiveLink output JSON must be an object.", failure_category="result_parse_error")
        status = str(payload.get("status", "ok"))
        if status not in {"ok", "evaluated"}:
            errors = _as_string_list(payload.get("errors"))
            message = "; ".join(errors) if errors else f"MATLAB LiveLink returned status {status!r}."
            failure_category = str(payload.get("failure_category") or _classify_matlab_process_failure(message))
            raise BackendExecutionError(message, failure_category=failure_category, warnings=_as_string_list(payload.get("warnings")))
        return payload

    def _simulation_output_from_payload(self, payload: dict[str, Any], problem_spec: dict[str, Any], model_profile: dict[str, Any]) -> dict[str, Any]:
        simulation_output = payload.get("simulation_output") or {}
        if not isinstance(simulation_output, dict):
            raise BackendExecutionError("simulation_output must be an object.", failure_category="result_parse_error")

        artifacts = _collect_artifacts(payload, simulation_output)
        parser_name = _parser_name(model_profile)
        if artifacts.get("table_path"):
            table_path = Path(str(artifacts["table_path"]))
            if table_path.exists():
                try:
                    if parser_name == "comsol_table":
                        parsed = parse_comsol_table_file(
                            table_path,
                            wavelengths_nm=(problem_spec.get("independent_variables") or {}).get("wavelength_nm") or None,
                            wavelength_match_tolerance_nm=_wavelength_match_tolerance_nm(model_profile),
                        )
                    else:
                        plugin = self._parser_registry.get("parsers", parser_name)
                        parsed = self._parser_registry.call(
                            plugin,
                            table_path,
                            columns=_output_columns(model_profile),
                            wavelengths_nm=(problem_spec.get("independent_variables") or {}).get("wavelength_nm") or None,
                            wavelength_match_tolerance_nm=_wavelength_match_tolerance_nm(model_profile),
                        )
                except (OSError, ValueError, KeyError, ImportError) as exc:
                    raise BackendExecutionError(
                        f"Failed to parse exported COMSOL table {table_path}: {exc}",
                        failure_category="result_parse_error",
                    ) from exc
                reserved = {"model_facts", "measurements", "recomputed_solutions"} & set(parsed)
                if reserved:
                    raise BackendExecutionError(
                        f"Table parser attempted to replace observed model evidence: {sorted(reserved)}",
                        failure_category="result_parse_error",
                    )
                simulation_output = {**simulation_output, **parsed}

        if "data_by_lam" in simulation_output:
            simulation_output["data_by_lam"] = _normalize_data_by_lam(simulation_output["data_by_lam"])
            simulation_output.setdefault("summary_metrics", {})
            simulation_output["summary_metrics"].setdefault(
                "mean_transmission",
                _mean_transmission(simulation_output["data_by_lam"]),
            )
        if artifacts:
            simulation_output.setdefault("artifacts", {}).update(artifacts)
        return simulation_output


def _validate_measurement_ids(values: Any, definitions: list[dict]) -> None:
    if values is None and not definitions:
        return
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise BackendExecutionError("Expected an array of named measurement results.", failure_category="measurement_failed")
    if sorted(item.get("id", "") for item in values) != sorted(item["id"] for item in definitions):
        raise BackendExecutionError("Returned measurements do not match the requested definitions.", failure_category="measurement_failed")


def _allowed_model_bindings(model_bindings: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {"parameters", "tags", "sweeps", "shape_switch", "material_switch", "feature_switches", "outputs"}
    return {key: copy.deepcopy(value) for key, value in model_bindings.items() if key in allowed_keys}


def _parser_name(model_profile: dict[str, Any]) -> str:
    outputs = ((model_profile.get("model_bindings") or {}).get("outputs") or {})
    if isinstance(outputs, dict):
        return str(outputs.get("parser") or "comsol_table")
    return "comsol_table"


def _output_columns(model_profile: dict[str, Any]) -> dict[str, Any] | None:
    outputs = ((model_profile.get("model_bindings") or {}).get("outputs") or {})
    if isinstance(outputs, dict) and isinstance(outputs.get("columns"), dict):
        return copy.deepcopy(outputs["columns"])
    return None


def _wavelength_match_tolerance_nm(model_profile: dict[str, Any]) -> float:
    outputs = ((model_profile.get("model_bindings") or {}).get("outputs") or {})
    raw_value = (
        outputs.get("wavelength_match_tolerance_nm", DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM)
        if isinstance(outputs, dict)
        else DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM
    )
    if isinstance(raw_value, bool):
        raise ValueError("model_bindings.outputs.wavelength_match_tolerance_nm must be a finite non-negative number.")
    try:
        tolerance = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "model_bindings.outputs.wavelength_match_tolerance_nm must be a finite non-negative number."
        ) from exc
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("model_bindings.outputs.wavelength_match_tolerance_nm must be a finite non-negative number.")
    return tolerance


def _resolve_required_path_env(env_name: str, *, must_exist: bool) -> Path:
    value = os.environ.get(env_name)
    if not value:
        raise BackendConfigurationError(f"Required environment variable {env_name!r} is not set.")
    path = Path(value).expanduser()
    if must_exist and not path.exists():
        raise BackendConfigurationError(f"Path from environment variable {env_name!r} does not exist: {path}")
    return path


def _resolve_optional_env(env_name: str | None, *, default: str | None = None) -> str | None:
    if not env_name:
        return default
    return os.environ.get(env_name) or default


def _ensure_directory(path: Path, description: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackendConfigurationError(f"Unable to create {description}: {path}") from exc


def _write_process_logs(run_dir: Path, stdout: Any, stderr: Any) -> None:
    for name, value in (("matlab_stdout.log", stdout), ("matlab_stderr.log", stderr)):
        if isinstance(value, bytes):
            text = value.decode(errors="replace")
        else:
            text = str(value or "")
        (run_dir / name).write_text(text, encoding="utf-8")




def _matlab_string(value: str) -> str:
    return "'" + value.replace("'", "''").replace("\\", "/") + "'"


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _collect_artifacts(payload: dict[str, Any], simulation_output: dict[str, Any]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for source in (payload.get("artifacts"), simulation_output.get("artifacts")):
        if isinstance(source, dict):
            artifacts.update(source)
    return artifacts


def _normalize_data_by_lam(raw: Any) -> dict[str, dict[str, list[float]]]:
    normalized: dict[str, dict[str, list[float]]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "wavelength_nm" in item:
                normalized[_format_wavelength_key(item["wavelength_nm"])] = _normalize_series(item)
        return normalized

    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            wavelength_key = _format_wavelength_key(value.get("wavelength_nm", _coerce_wavelength_key(key)))
            normalized[wavelength_key] = _normalize_series(value)
    return normalized


def _normalize_series(series: dict[str, Any]) -> dict[str, list[float]]:
    return {
        "param_nm": _numeric_list(series.get("param_nm", series.get("param", series.get("l", [])))),
        "T": _numeric_list(series.get("T", series.get("transmission", []))),
        "phi_rad": _numeric_list(series.get("phi_rad", series.get("phi", series.get("phase_rad", [])))),
    }


def _numeric_list(value: Any) -> list[float]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    cleaned: list[float] = []
    for item in value:
        number = float(item)
        cleaned.append(int(number) if number.is_integer() else number)
    return cleaned


def _coerce_wavelength_key(key: Any) -> str:
    text = str(key).strip()
    for prefix in ("lambda_", "lam_", "wavelength_", "w_"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    if text.startswith("x") and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def _format_wavelength_key(value: Any) -> str:
    number = float(str(value).strip().lower().replace("nm", ""))
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _mean_transmission(data_by_lam: dict[str, dict[str, list[float]]]) -> float:
    values = [value for series in data_by_lam.values() for value in series.get("T", [])]
    return sum(values) / len(values) if values else 0.0


def _classify_matlab_process_failure(message: str) -> str:
    text = str(message).lower()
    if any(marker in text for marker in ("license checkout", "license manager", "license error", "no licenses available")):
        return "backend_license_error"
    if any(
        marker in text
        for marker in (
            "mphstart",
            "failed to connect to server",
            "connection refused",
            "could not connect to comsol",
            "comsol server",
        )
    ):
        return "backend_connection_error"
    if "timed out" in text or "timeout" in text:
        return "backend_timeout"
    if "mesh" in text:
        return "mesh_failure"
    if any(marker in text for marker in ("parse", "json", "table", "output json")):
        return "result_parse_error"
    if any(
        marker in text
        for marker in (
            "failed to find a solution",
            "solver",
            "nonconvergence",
            "not converged",
            "singular matrix",
        )
    ):
        return "solver_nonconvergence"
    return "backend_execution_error"
