from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..utils.paths import configured_design_package_roots
from ..utils.yaml_io import load_yaml_file


PACKAGE_MANIFEST = "em-design-package.yaml"
PACKAGE_SCHEMA_VERSION = "em_design_package_v1"
_PRUNED_DIRS = {".git", "__pycache__", "artifacts", "runs", "tmp"}


@dataclass(frozen=True)
class DesignPackage:
    package_id: str
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]

    def resolve_files(self, key: str) -> list[Path]:
        raw_entries = self.manifest.get(key) or []
        if not isinstance(raw_entries, list):
            raise ValueError(f"Package {self.package_id!r} field {key!r} must be a list.")
        resolved: list[Path] = []
        for raw_entry in raw_entries:
            entry = str(raw_entry).strip()
            if not entry:
                continue
            matches = sorted(self.root.glob(entry))
            if not matches:
                raise FileNotFoundError(
                    f"Package {self.package_id!r} {key} entry did not match a file: {entry}"
                )
            for path in matches:
                resolved_path = path.resolve()
                _require_within(resolved_path, self.root, f"{key} entry {entry!r}")
                if resolved_path.is_file():
                    resolved.append(resolved_path)
        return resolved


@dataclass(frozen=True)
class PackageFile:
    package: DesignPackage | None
    path: Path


@dataclass(frozen=True)
class PluginSpec:
    package: DesignPackage
    plugin_id: str
    kind: str
    path: Path
    callable_name: str
    metadata: dict[str, Any]


class PackageRegistry:
    """Discover versioned design packages outside the MCP tool repository."""

    def __init__(self, roots: Iterable[str | Path] | None = None) -> None:
        selected = list(roots) if roots is not None else configured_design_package_roots()
        self.roots = tuple(Path(root).expanduser().resolve() for root in selected)
        self._packages: tuple[DesignPackage, ...] | None = None

    def packages(self) -> tuple[DesignPackage, ...]:
        if self._packages is None:
            self._packages = tuple(self._discover())
        return self._packages

    def profile_files(self) -> list[PackageFile]:
        return [
            PackageFile(package=package, path=path)
            for package in self.packages()
            for path in package.resolve_files("profiles")
        ]

    def problem_files(self) -> list[PackageFile]:
        return [
            PackageFile(package=package, path=path)
            for package in self.packages()
            for path in package.resolve_files("problems")
        ]

    def plugin_specs(self, kind: str) -> list[PluginSpec]:
        specs: list[PluginSpec] = []
        for package in self.packages():
            plugins = package.manifest.get("plugins") or {}
            raw_specs = plugins.get(kind) if isinstance(plugins, dict) else None
            if raw_specs is None:
                continue
            if not isinstance(raw_specs, dict):
                raise ValueError(
                    f"Package {package.package_id!r} plugins.{kind} must be an object."
                )
            for plugin_id, raw_spec in raw_specs.items():
                if not isinstance(raw_spec, dict):
                    raise ValueError(
                        f"Package {package.package_id!r} plugin {plugin_id!r} must be an object."
                    )
                relative_path = str(raw_spec.get("path") or "").strip()
                callable_name = str(raw_spec.get("callable") or "").strip()
                if not relative_path or not callable_name:
                    raise ValueError(
                        f"Package {package.package_id!r} plugin {plugin_id!r} requires path and callable."
                    )
                path = (package.root / relative_path).resolve()
                _require_within(path, package.root, f"plugin {plugin_id!r}")
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Package {package.package_id!r} plugin file does not exist: {path}"
                    )
                specs.append(
                    PluginSpec(
                        package=package,
                        plugin_id=str(plugin_id),
                        kind=kind,
                        path=path,
                        callable_name=callable_name,
                        metadata={
                            str(key): value
                            for key, value in raw_spec.items()
                            if key not in {"path", "callable"}
                        },
                    )
                )
        return specs

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "package_id": package.package_id,
                "description": str(package.manifest.get("description") or ""),
                "root": str(package.root),
                "profile_count": len(package.resolve_files("profiles")),
                "problem_count": len(package.resolve_files("problems")),
            }
            for package in self.packages()
        ]

    def _discover(self) -> list[DesignPackage]:
        discovered: dict[str, DesignPackage] = {}
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            for manifest_path in _iter_manifests(root):
                manifest = load_yaml_file(manifest_path)
                if not isinstance(manifest, dict):
                    raise ValueError(f"Design package manifest must be an object: {manifest_path}")
                schema_version = str(manifest.get("schema_version") or "").strip()
                if schema_version != PACKAGE_SCHEMA_VERSION:
                    raise ValueError(
                        f"Unsupported package schema {schema_version!r} in {manifest_path}; "
                        f"expected {PACKAGE_SCHEMA_VERSION!r}."
                    )
                package_id = str(manifest.get("package_id") or "").strip()
                if not package_id:
                    raise ValueError(f"Design package is missing package_id: {manifest_path}")
                if package_id in discovered:
                    raise ValueError(
                        f"Duplicate package_id {package_id!r}: "
                        f"{discovered[package_id].manifest_path} and {manifest_path}"
                    )
                discovered[package_id] = DesignPackage(
                    package_id=package_id,
                    root=manifest_path.parent.resolve(),
                    manifest_path=manifest_path.resolve(),
                    manifest=manifest,
                )
        return [discovered[key] for key in sorted(discovered)]


def _iter_manifests(root: Path):
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _PRUNED_DIRS and (not name.startswith(".") or name == ".em-design")
        ]
        if PACKAGE_MANIFEST in filenames:
            yield Path(directory) / PACKAGE_MANIFEST


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Package {label} resolves outside package root: {path}") from exc
