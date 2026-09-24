from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..registries.model_profile_registry import ModelProfileRegistry
from ..registries.package_registry import PackageRegistry
from ..registries.problem_spec_registry import ProblemSpecRegistry
from ..utils.paths import DESIGN_PACKAGE_ROOTS_ENV, RUNS_DIR_ENV, configured_run_root, configured_runs_dir
from ..utils.provenance import capture_provenance, compact_provenance, file_sha256, require_provenance
from ..schemas.model_observation import selected_measurements, validate_topics


TERMINAL_STATUSES = {"evaluated", "verifier_failed", "validation_failed", "policy_failed", "backend_failed", "backend_not_implemented", "cancelled", "worker_failed", "inspected", "preflight_failed", "stale_provenance"}


class JobStore:
    def __init__(
        self,
        packages: PackageRegistry,
        model_profiles: ModelProfileRegistry,
    ) -> None:
        self.packages = packages
        self.model_profiles = model_profiles

    def start_inspection(self, *, model_profile_id: str, problem_id: str | None = None,
                         topics: list[str] | None = None, measurement_ids: list[str] | None = None,
                         source_job_id: str | None = None, wait_seconds: float = 20.0) -> dict:
        topics = validate_topics(topics)
        profile = self.model_profiles.as_dict(model_profile_id)
        selected_measurements(profile, measurement_ids or [])
        source = None
        expected = None
        if source_job_id:
            source_dir = self._find_job_dir(source_job_id)
            source_request = _read_json(source_dir / "request.json")
            if source_request["model_profile_id"] != model_profile_id:
                raise ValueError("Source run belongs to a different model profile.")
            if problem_id and problem_id != source_request["problem_id"]:
                raise ValueError("Source run belongs to a different problem contract.")
            problem_id = source_request["problem_id"]
            source_state = _read_json(source_dir / "state.json")
            if source_state.get("status") not in {"evaluated", "verifier_failed"}:
                raise ValueError("Source run must have completed a solver evaluation.")
            result = _read_json(source_dir / "result.json")
            artifact = (result.get("simulation_output") or {}).get("artifacts") or {}
            path, digest = artifact.get("solved_model_path"), artifact.get("solved_model_sha256")
            expected = result.get("provenance")
            if not path or not digest or not expected:
                raise ValueError("Source run has no saved solved artifact with verified provenance. Enable save_solved_model for the producing run.")
            if file_sha256(path) != digest:
                raise ValueError("Source solved model was modified after the run.")
            source = {"job_id": source_job_id, "revision": source_state["revision"], "path": path, "sha256": digest,
                      "recomputed_solutions": (result.get("simulation_output") or {}).get("recomputed_solutions") or []}
        return self.start(model_profile_id=model_profile_id, problem_id=problem_id or "",
                          candidate={}, backend="matlab_livelink", wait_seconds=wait_seconds,
                          action="inspect", topics=topics, measurement_ids=measurement_ids or [],
                          source=source, expected_provenance=expected)

    def start(
        self,
        *,
        model_profile_id: str,
        problem_id: str,
        candidate: dict[str, Any],
        backend: str,
        wait_seconds: float = 20.0,
        action: str = "evaluate",
        topics: list[str] | None = None,
        measurement_ids: list[str] | None = None,
        source: dict | None = None,
        expected_provenance: dict | str | None = None,
    ) -> dict[str, Any]:
        profile = self.model_profiles.as_dict(model_profile_id)
        problem = ProblemSpecRegistry(packages=self.packages).as_dict(problem_id) if problem_id else {}
        provenance = capture_provenance(profile, problem, self.packages)
        require_provenance(expected_provenance, provenance)
        job_id = _make_job_id(model_profile_id, problem_id)
        job_dir = configured_run_root(profile) / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        request = {
            "job_id": job_id,
            "model_profile_id": model_profile_id,
            "problem_id": problem_id,
            "candidate": candidate,
            "backend": backend,
            "created_at": _now(),
            "action": action,
            "topics": topics,
            "measurement_ids": measurement_ids or [],
            "source": source,
            "provenance": provenance,
            "profile_snapshot": profile,
            "problem_snapshot": problem,
        }
        request_path = job_dir / "request.json"
        state_path = job_dir / "state.json"
        _write_json(request_path, request)
        _write_json(
            state_path,
            {
                "schema_version": "em_design_job_v1",
                "job_id": job_id,
                "status": "running",
                "revision": 1,
                "created_at": request["created_at"],
                "updated_at": request["created_at"],
                "provenance_id": provenance["id"],
            },
        )
        command = [
            sys.executable,
            "-m",
            "em_design_mcp.worker",
            "--request",
            str(request_path),
            "--state",
            str(state_path),
        ]
        # Workers change directory, so preserve the caller's selected roots as
        # absolute paths. Explicit PackageRegistry roots take precedence over
        # inherited environment configuration without mutating the server env.
        worker_env = os.environ.copy()
        worker_env[DESIGN_PACKAGE_ROOTS_ENV] = os.pathsep.join(str(root) for root in self.packages.roots)
        worker_env[RUNS_DIR_ENV] = str(job_dir.parent)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=str(job_dir),
                env=worker_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except Exception as exc:
            update_state(state_path, status="worker_failed", message=f"Unable to start worker: {exc}")
            return self.get(job_id)
        _write_json(job_dir / "pid.json", {"pid": process.pid})
        return self.get(job_id, wait_seconds=wait_seconds, after_revision=1)

    def get(
        self,
        job_id: str,
        *,
        wait_seconds: float = 0.0,
        after_revision: int = 0,
        include_result: bool = False,
    ) -> dict[str, Any]:
        job_dir = self._find_job_dir(job_id)
        state_path = job_dir / "state.json"
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 55.0))
        state = _read_json(state_path)
        while (
            int(state.get("revision") or 0) <= int(after_revision)
            and state.get("status") not in TERMINAL_STATUSES
            and time.monotonic() < deadline
        ):
            time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))
            state = _read_json(state_path)
        return _compact_job(job_dir, state, include_result=include_result)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job_dir = self._find_job_dir(job_id)
        state_path = job_dir / "state.json"
        state = _read_json(state_path)
        if state.get("status") in TERMINAL_STATUSES:
            return _compact_job(job_dir, state, include_result=False)
        pid_path = job_dir / "pid.json"
        pid_payload = _read_json(pid_path) if pid_path.is_file() else {}
        pid = int(pid_payload.get("pid") or 0)
        if pid > 0:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
        state.update(
            {
                "status": "cancelled",
                "revision": int(state.get("revision") or 0) + 1,
                "updated_at": _now(),
            }
        )
        _write_json(state_path, state)
        return _compact_job(job_dir, state, include_result=False)

    def _find_job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("job_") or any(value in job_id for value in ("/", "\\", "..")):
            raise ValueError("Invalid job_id.")
        roots = [configured_runs_dir()]
        roots.extend(package.root / "runs" for package in self.packages.packages())
        for root in roots:
            candidate = root / job_id
            if (candidate / "state.json").is_file():
                return candidate
        raise KeyError(f"Unknown job_id: {job_id}")


def update_state(state_path: Path, **changes: Any) -> dict[str, Any]:
    state = _read_json(state_path)
    if state.get("status") == "cancelled" and changes.get("status") != "cancelled":
        return state
    state.update(changes)
    state["revision"] = int(state.get("revision") or 0) + 1
    state["updated_at"] = _now()
    _write_json(state_path, state)
    return state


def _compact_job(job_dir: Path, state: dict[str, Any], *, include_result: bool) -> dict[str, Any]:
    payload = {
        "job_id": state.get("job_id"),
        "status": state.get("status"),
        "revision": int(state.get("revision") or 0),
        "terminal": state.get("status") in TERMINAL_STATUSES,
        "updated_at": state.get("updated_at"),
        "run_dir": str(job_dir),
        "provenance_id": state.get("provenance_id"),
    }
    if state.get("message"):
        payload["message"] = state["message"]
    result_path = job_dir / "result.json"
    if result_path.is_file():
        result = _read_json(result_path)
        verifier = result.get("verifier_result") if isinstance(result.get("verifier_result"), dict) else {}
        payload.update(
            {
                "overall_pass": result.get("overall_pass"),
                "failure_category": result.get("failure_category"),
                "summary_metrics": (
                    verifier.get("summary_metrics")
                    or (result.get("simulation_output") or {}).get("summary_metrics")
                    or {}
                ),
                "verifier_feedback": {
                    key: verifier[key]
                    for key in (
                        "overall_pass_relaxed",
                        "overall_pass_nominal",
                        "overall_pass_strict",
                        "continuous_score",
                        "limiting_constraint",
                        "agent_feedback",
                        "normalized_margins",
                        "hard_constraint_margins",
                    )
                    if key in verifier
                },
                "warnings": list(result.get("warnings") or []),
                "errors": list(result.get("errors") or []),
                "result_path": str(result_path),
            }
        )
        if result.get("provenance"):
            payload["provenance"] = compact_provenance(result["provenance"])
        from ..tools.model_tools import compact, compact_inspection
        for name in ("summary_metrics", "verifier_feedback", "warnings", "errors"):
            payload[name] = compact(payload[name])
        if "facts" in result:
            payload.update(compact_inspection(result))
        else:
            output = result.get("simulation_output") or {}
            for name in ("preflight", "measurements", "solution_freshness", "recomputed_solutions", "artifacts"):
                if name in output:
                    payload[name] = compact(output[name])
        if include_result:
            payload["result"] = result
    return payload


def _make_job_id(model_profile_id: str, problem_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_profile = "".join(ch if ch.isalnum() else "-" for ch in model_profile_id)[:24]
    safe_problem = "".join(ch if ch.isalnum() else "-" for ch in problem_id)[:24]
    return f"job_{timestamp}_{safe_profile}_{safe_problem}_{uuid.uuid4().hex[:8]}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
