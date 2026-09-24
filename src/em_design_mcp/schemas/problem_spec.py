from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProblemSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    problem_id: str
    version: str
    family: str
    difficulty: str
    description: str
    compatible_model_profiles: list[str]
    independent_variables: dict[str, list[Any]]
    objectives: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    verifier_id: str
    expected_outputs: list[str]
    candidate_schema_overrides: dict[str, Any] | None = None
    execution_policy: dict[str, Any] | None = None
