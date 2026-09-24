"""Content fingerprints for the actual inputs to a run, including trusted plugins."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..backends.base import BackendConfigurationError, BackendExecutionError
from ..registries.package_registry import PackageRegistry
from .contract_metadata import build_contract_metadata, stable_contract_hash
from .paths import project_path, resolve_package_path


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_path(profile: dict) -> Path:
    artifact = (profile.get("backend") or {}).get("model_artifact") or {}
    value = artifact.get("path") or os.environ.get(artifact.get("path_env") or "")
    if not value:
        raise BackendConfigurationError("The model artifact path is not configured.")
    path = resolve_package_path(value, profile.get("_package_root")).resolve()
    if not path.is_file():
        raise BackendConfigurationError(f"Model artifact does not exist: {path}")
    return path


def capture_provenance(profile: dict, problem: dict, packages: PackageRegistry | None = None) -> dict:
    packages = packages or PackageRegistry()
    files: set[Path] = set()
    artifact = (profile.get("backend") or {}).get("model_artifact") or {}
    model = None
    if (profile.get("backend") or {}).get("type") == "matlab_livelink":
        model = model_path(profile)
        files.add(model)
    for spec in (profile, problem):
        if spec.get("_source_path"):
            files.add(Path(spec["_source_path"]).resolve())
        root = spec.get("_package_root")
        if root:
            files.add(Path(root) / "em-design-package.yaml")
        for value in spec.get("provenance_files") or []:
            files.add(resolve_package_path(value, root).resolve())
    for value in artifact.get("companion_paths") or []:
        files.add(resolve_package_path(value, profile.get("_package_root")).resolve())
    for name in artifact.get("companion_paths_env") or []:
        if os.environ.get(name):
            files.add(Path(os.environ[name]).resolve())
    parser = ((profile.get("model_bindings") or {}).get("outputs") or {}).get("parser", "comsol_table")
    verifier_version = None
    for kind, plugin_id in (("parsers", parser), ("verifiers", problem.get("verifier_id"))):
        if not plugin_id or (kind == "parsers" and plugin_id == "comsol_table"):
            continue
        matches = [spec for spec in packages.plugin_specs(kind) if spec.plugin_id == plugin_id]
        if len(matches) != 1:
            raise BackendConfigurationError(f"Expected one {kind} plugin {plugin_id!r}, found {len(matches)}.")
        plugin = matches[0]
        if kind == "verifiers":
            verifier_version = str(plugin.metadata.get("version") or "0.1")
        files.add(plugin.package.manifest_path)
        files.add(plugin.path)
        # Includes Python helper imports adjacent to a registered entrypoint.
        files.update(plugin.path.parent.rglob("*.py"))
    files.update(project_path("src", "em_design_mcp").rglob("*.py"))
    for name in ("run_em_design_from_json.m", "em_model_facts.m", "em_named_measurements.m"):
        files.add(project_path("matlab", name))
    hashes = {}
    for path in sorted(files):
        try:
            hashes[str(path.resolve())] = file_sha256(path)
        except OSError as exc:
            raise BackendConfigurationError(f"Cannot fingerprint declared dependency {path}: {exc}") from exc
    contract = build_contract_metadata(profile, problem, verifier_version=verifier_version)
    identity = {"contract_hash": contract["contract_hash"], "files": hashes}
    return {
        "schema_version": "em_provenance_v1",
        "id": stable_contract_hash(identity),
        **identity,
        "model": {"path": str(model), "sha256": hashes[str(model)]} if model else None,
    }


def require_provenance(expected: dict | str | None, actual: dict) -> None:
    expected_id = expected.get("id") if isinstance(expected, dict) else expected
    if expected_id and expected_id != actual["id"]:
        raise BackendExecutionError(
            "Model, contract, runner, plugin code, or declared validation evidence changed. Re-inspect the contract before running or reusing this result.",
            failure_category="stale_provenance",
        )


def compact_provenance(value: dict) -> dict:
    return {key: value[key] for key in ("schema_version", "id", "contract_hash", "model") if key in value}
