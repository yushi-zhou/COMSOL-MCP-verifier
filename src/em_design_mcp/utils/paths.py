from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = PACKAGE_ROOT.parent
RUNS_DIR_ENV = "EM_DESIGN_MCP_RUNS_DIR"
DESIGN_PACKAGE_ROOTS_ENV = "EM_DESIGN_PACKAGE_ROOTS"

DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_DESIGN_PACKAGE_ROOT = PROJECT_ROOT.parent / "em_design_modals"


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def configured_runs_dir() -> Path:
    return _configured_dir(RUNS_DIR_ENV, DEFAULT_RUNS_DIR)


def configured_design_package_roots() -> list[Path]:
    """Return package search roots without requiring machine-specific paths."""
    configured = os.environ.get(DESIGN_PACKAGE_ROOTS_ENV)
    if configured:
        return [
            Path(value).expanduser().resolve()
            for value in configured.split(os.pathsep)
            if value.strip()
        ]
    return [DEFAULT_DESIGN_PACKAGE_ROOT]


def resolve_package_path(value: str | Path, package_root: str | Path | None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or package_root is None:
        return path
    return Path(package_root) / path


def configured_run_root(model_profile: dict | None = None) -> Path:
    if os.environ.get(RUNS_DIR_ENV):
        return configured_runs_dir()
    if model_profile and model_profile.get("_package_root"):
        return (Path(str(model_profile["_package_root"])) / "runs").resolve()
    return configured_runs_dir()


def _configured_dir(env_var: str, default: Path) -> Path:
    configured = os.environ.get(env_var)
    if configured:
        return Path(configured).expanduser().resolve()
    return default
