from __future__ import annotations

import argparse
import json
from pathlib import Path

from .registries.model_profile_registry import ModelProfileRegistry
from .registries.package_registry import PackageRegistry
from .registries.problem_spec_registry import ProblemSpecRegistry
from .registries.verifier_registry import VerifierRegistry
from .runs.job_store import update_state
from .tools.candidate_tools import evaluate_candidate_payload
from .utils.dotenv import load_project_dotenv
from .utils.provenance import capture_provenance, require_provenance
from .backends.base import BackendError
from .tools.model_tools import inspect_model_payload
from .runs.job_store import _write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request).resolve()
    state_path = Path(args.state).resolve()
    result_path = request_path.parent / "result.json"
    try:
        load_project_dotenv()
        request = json.loads(request_path.read_text(encoding="utf-8"))
        packages = PackageRegistry()
        profiles = ModelProfileRegistry(packages=packages)
        problems = ProblemSpecRegistry(packages=packages)
        verifiers = VerifierRegistry(packages)
        profile = profiles.as_dict(str(request["model_profile_id"]))
        problem = problems.as_dict(str(request["problem_id"])) if request.get("problem_id") else {}
        require_provenance(request.get("provenance"), capture_provenance(profile, problem, packages))
        if request.get("action") == "inspect":
            result = inspect_model_payload(request, profile, problem, packages)
        else:
            result = evaluate_candidate_payload(
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
        _write_json(result_path, result)
        update_state(state_path, status=str(result.get("status") or "evaluated"), result_path=str(result_path))
        return 0
    except BackendError as exc:
        status = "stale_provenance" if exc.failure_category == "stale_provenance" else "backend_failed"
        _write_json(result_path, {"status": status, "failure_category": exc.failure_category, "errors": [str(exc)], "overall_pass": False})
        update_state(state_path, status=status, message=str(exc), result_path=str(result_path))
        return 1
    except Exception as exc:
        update_state(state_path, status="worker_failed", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
