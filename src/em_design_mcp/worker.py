from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
from typing import Any

from .backends.base import BackendError
from .registries.model_profile_registry import ModelProfileRegistry
from .registries.package_registry import PackageRegistry
from .registries.problem_spec_registry import ProblemSpecRegistry
from .registries.verifier_registry import VerifierRegistry
from .runs.job_store import finalize_job, update_state
from .tools.candidate_tools import evaluate_candidate_payload
from .tools.model_tools import inspect_model_payload
from .utils.dotenv import load_project_dotenv
from .utils.file_lock import comsol_execution_slot
from .utils.process_tree import install_termination_forwarding
from .utils.provenance import capture_provenance, require_provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request).resolve()
    state_path = Path(args.state).resolve()
    result_path = request_path.parent / "result.json"
    install_termination_forwarding()
    try:
        load_project_dotenv()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        with _solver_slot(request, state_path):
            result = _execute(request)
        finalize_job(state_path, result_path, result)
        return 0
    except BackendError as exc:
        status = "stale_provenance" if exc.failure_category == "stale_provenance" else "backend_failed"
        finalize_job(
            state_path,
            result_path,
            {"status": status, "failure_category": exc.failure_category, "errors": [str(exc)], "overall_pass": False},
            message=str(exc),
        )
        return 1
    except Exception as exc:
        update_state(state_path, status="worker_failed", message=f"{type(exc).__name__}: {exc}")
        return 1


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    packages = PackageRegistry()
    profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)
    profile = profiles.as_dict(str(request["model_profile_id"]))
    problem = problems.as_dict(str(request["problem_id"])) if request.get("problem_id") else {}
    require_provenance(request.get("provenance"), capture_provenance(profile, problem, packages))
    if request.get("action") == "inspect":
        return inspect_model_payload(request, profile, problem, packages)
    return evaluate_candidate_payload(
        str(request["model_profile_id"]),
        str(request["problem_id"]),
        dict(request["candidate"]),
        str(request["backend"]),
        profiles,
        problems,
        verifiers,
        run_id_override=str(request["job_id"]),
        expected_provenance=request.get("provenance"),
    )


def _solver_slot(request: dict[str, Any], state_path: Path):
    """Run COMSOL-using jobs one at a time per local server; report waiting as queued."""
    if str(request.get("backend") or "") != "matlab_livelink":
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def slot():
        def mark_queued() -> None:
            update_state(state_path, status="queued", message="Waiting for another job using the same COMSOL server.")

        with comsol_execution_slot(on_wait=mark_queued) as waited:
            if waited:
                update_state(state_path, status="running", message="")
            yield

    return slot()


if __name__ == "__main__":
    raise SystemExit(main())
