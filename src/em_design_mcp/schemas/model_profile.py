from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .model_observation import Measurement, PreflightCheck


class BackendArtifactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    path: str | None = None
    path_env: str | None = None
    companion_paths: list[str] = Field(default_factory=list)
    companion_paths_env: list[str] = Field(default_factory=list)


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    model_artifact: BackendArtifactConfig
    output_dir: str | None = None
    output_dir_env: str | None = None
    matlab_executable_env: str | None = None
    comsol_mli_env: str | None = None


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str
    version: str
    domain: str
    description: str
    backend: BackendConfig
    compatible_problem_families: list[str]
    design_schema: dict[str, Any]
    mock_generation: dict[str, Any] | None = None
    model_bindings: dict[str, Any]
    output_schema: dict[str, Any]
    execution_policy: dict[str, Any] | None = None
    preflight: list[PreflightCheck] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    provenance_files: list[str] = Field(default_factory=list)
