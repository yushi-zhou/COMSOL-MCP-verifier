from __future__ import annotations

import functools
from typing import Any, Callable

import anyio
from mcp.types import ToolAnnotations

from ..registries.model_profile_registry import ModelProfileRegistry
from ..registries.package_registry import PackageRegistry
from ..registries.problem_spec_registry import ProblemSpecRegistry
from ..registries.verifier_registry import VerifierRegistry
from ..runs.job_store import JobStore
from ..utils.provenance import capture_provenance, compact_provenance
from .candidate_tools import (
    estimate_candidate_cost_payload,
    get_contract_bundle_payload,
)


def register_agent_tools(
    server,
    packages: PackageRegistry,
    profiles: ModelProfileRegistry,
    problems: ProblemSpecRegistry,
    verifiers: VerifierRegistry,
) -> None:
    # FastMCP calls synchronous tools on its event loop. Every tool is therefore
    # async: file I/O, hashing and plugin loading run in worker threads, and
    # long-polls sleep cooperatively, so one wait never stalls other requests.
    def current():
        # Each request sees the current package manifests and contracts. Workers
        # validate their recorded fingerprint again before using these files.
        active_packages = PackageRegistry(roots=packages.roots)
        active_profiles = ModelProfileRegistry(root_dir=profiles.root_dir, packages=active_packages)
        active_problems = ProblemSpecRegistry(root_dir=problems.root_dir, packages=active_packages)
        return (active_packages, active_profiles, active_problems,
                VerifierRegistry(active_packages), JobStore(active_packages, active_profiles))

    def discover(query: str) -> dict[str, Any]:
        packages, profiles, problems, _, _ = current()
        needle = query.strip().lower()
        problem_index = {item["problem_id"]: item for item in problems.list_specs()}
        designs: list[dict[str, Any]] = []
        for summary in profiles.list_profiles():
            profile = profiles.as_dict(summary["model_profile_id"])
            compatible = [
                problem_id
                for problem_id in problem_index
                if summary["model_profile_id"]
                in problems.as_dict(problem_id).get("compatible_model_profiles", [])
            ]
            row = {
                **summary,
                "package_id": profile.get("_package_id"),
                "backend": (profile.get("backend") or {}).get("type"),
                "problem_ids": compatible,
            }
            searchable = " ".join(str(value) for value in row.values()).lower()
            if not needle or needle in searchable:
                designs.append(row)
        return {"packages": packages.summary(), "designs": designs, "count": len(designs)}

    def contract(model_profile_id: str, problem_id: str) -> dict[str, Any]:
        _, profiles, problems, verifiers, _ = current()
        bundle = get_contract_bundle_payload(model_profile_id, problem_id, profiles, problems, verifiers)
        profile = profiles.as_dict(model_profile_id)
        problem = problems.as_dict(problem_id)
        bundle["package"] = {
            "package_id": profile.get("_package_id"),
            "root": profile.get("_package_root"),
            "profile_source": profile.get("_source_path"),
            "problem_source": problem.get("_source_path"),
        }
        return bundle

    def prepare(model_profile_id: str, problem_id: str, candidate: dict[str, Any], backend: str) -> dict[str, Any]:
        packages, profiles, problems, verifiers, _ = current()
        estimate = estimate_candidate_cost_payload(
            model_profile_id, problem_id, candidate, backend, profiles, problems, verifiers
        )
        validation = estimate["validation"]
        return {
            "valid": bool(validation["valid"] and estimate["valid"]),
            "normalized_candidate": validation["normalized_candidate"],
            "estimated_sweep_points": estimate.get("estimated_sweep_points"),
            "estimated_conditions": estimate.get("estimated_conditions"),
            "policy_applied": estimate.get("policy_applied") or {},
            "warnings": estimate.get("warnings") or [],
            "errors": estimate.get("errors") or [],
            "provenance": compact_provenance(capture_provenance(
                profiles.as_dict(model_profile_id), problems.as_dict(problem_id), packages
            )),
        }

    @server.tool(
        name="discover_designs",
        description="List compact model/problem pairs. Call once before selecting a contract.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def discover_designs(query: str = "") -> dict[str, Any]:
        return await _in_thread(discover, query)

    @server.tool(
        name="inspect_contract",
        description="Return the candidate schema, allowed ranges, objectives, outputs, verifier, and immutable contract hash for one design task.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def inspect_contract(model_profile_id: str, problem_id: str) -> dict[str, Any]:
        return await _in_thread(contract, model_profile_id, problem_id)

    @server.tool(
        name="inspect_model",
        description=(
            "Read actual COMSOL facts by topic: studies (including solutions/datasets), physics, "
            "excitation, periodic, materials, selections, mesh, outputs. Optionally evaluate package-owned "
            "measurement_ids. No solve or model edits. source_job_id selects a verified saved run artifact; "
            "otherwise saved-solution freshness is unknown. Uses the existing persistent job/wait workflow."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def inspect_model(
        model_profile_id: str,
        topics: list[str] | None = None,
        measurement_ids: list[str] | None = None,
        problem_id: str | None = None,
        source_job_id: str | None = None,
        wait_seconds: float = 20.0,
    ) -> dict[str, Any]:
        jobs = current()[4]
        started = await _in_thread(
            jobs.start_inspection,
            model_profile_id=model_profile_id, problem_id=problem_id, topics=topics,
            measurement_ids=measurement_ids, source_job_id=source_job_id, wait_seconds=0,
        )
        return await _follow(jobs, started, wait_seconds)

    @server.tool(
        name="prepare_run",
        description="Validate a candidate and estimate real-solver cost without starting COMSOL.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def prepare_run(
        model_profile_id: str,
        problem_id: str,
        candidate: dict[str, Any],
        backend: str = "matlab_livelink",
    ) -> dict[str, Any]:
        return await _in_thread(prepare, model_profile_id, problem_id, candidate, backend)

    @server.tool(
        name="start_run",
        description="Start a persistent simulation worker and wait server-side for a quick result. Use the returned revision with get_run if still running.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def start_run(
        model_profile_id: str,
        problem_id: str,
        candidate: dict[str, Any],
        backend: str = "matlab_livelink",
        wait_seconds: float = 20.0,
        provenance_id: str | None = None,
    ) -> dict[str, Any]:
        prepared = await _in_thread(prepare, model_profile_id, problem_id, candidate, backend)
        if not prepared["valid"]:
            return {"status": "validation_failed", "terminal": True, **prepared}
        jobs = current()[4]
        started = await _in_thread(
            jobs.start,
            model_profile_id=model_profile_id,
            problem_id=problem_id,
            candidate=prepared["normalized_candidate"],
            backend=backend,
            wait_seconds=0,
            expected_provenance=provenance_id or prepared["provenance"]["id"],
        )
        return await _follow(jobs, started, wait_seconds)

    @server.tool(
        name="get_run",
        description="Long-poll one job by revision. Defaults to a compact result; request include_result only when full arrays are needed.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def get_run(
        job_id: str,
        after_revision: int = 0,
        wait_seconds: float = 30.0,
        include_result: bool = False,
    ) -> dict[str, Any]:
        return await current()[4].wait(
            job_id,
            wait_seconds=wait_seconds,
            after_revision=after_revision,
            include_result=include_result,
        )

    @server.tool(
        name="cancel_run",
        description="Request best-effort termination of the recorded worker process tree for one active job.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def cancel_run(job_id: str) -> dict[str, Any]:
        return await _in_thread(current()[4].cancel, job_id)


async def _in_thread(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await anyio.to_thread.run_sync(functools.partial(function, *args, **kwargs))


async def _follow(jobs: JobStore, started: dict[str, Any], wait_seconds: float) -> dict[str, Any]:
    if started.get("terminal"):
        return started
    return await jobs.wait(
        str(started["job_id"]),
        wait_seconds=wait_seconds,
        after_revision=int(started.get("revision") or 0),
    )
