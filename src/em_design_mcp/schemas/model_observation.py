"""Small, package-owned observation contracts. No executable commands."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MODEL_TOPICS = ("studies", "physics", "excitation", "periodic", "materials", "selections", "mesh", "outputs")
CHECK_TOPICS = {
    "physics_active": ("physics",),
    "excitation": ("excitation",),
    "periodic": ("periodic",),
    "selection_nonempty": ("selections",),
    "material_selection": ("materials", "selections"),
    "dataset_binding": ("studies",),
    "mesh_present": ("mesh",),
}


class Normalization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    expression: str = Field(min_length=1)
    method: Literal["global", "integrate", "average", "maximum"]
    study: str = Field(min_length=1)
    solution: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    selection: str = ""
    dimension: Literal["volume", "surface", "line"] | None = None
    normalization: Normalization | None = None
    solnum: int | Literal["all"] = "all"
    outersolnum: int | Literal["all"] = "all"

    @field_validator("solnum", "outersolnum", mode="before")
    @classmethod
    def solution_index(cls, value):
        if value != "all" and (type(value) is not int or value < 1):
            raise ValueError("Solution selectors must be 'all' or a positive integer.")
        return value

    @model_validator(mode="after")
    def spatial_binding(self):
        if self.method != "global" and (not self.selection or self.dimension is None):
            raise ValueError("Spatial measurements require a named selection and dimension.")
        if self.method == "global" and (self.selection or self.dimension is not None):
            raise ValueError("Global measurements cannot silently ignore a selection/dimension.")
        return self


class ExpectedScalar(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float
    unit: str = Field(min_length=1)
    atol: float = Field(default=0.0, ge=0)


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    kind: Literal["physics_active", "excitation", "periodic", "selection_nonempty", "material_selection", "dataset_binding", "mesh_present"]
    target: str = Field(min_length=1)
    expected: dict[str, Any] = Field(default_factory=dict)
    expected_values: dict[str, ExpectedScalar] = Field(default_factory=dict)
    study: str | None = None
    solution: str | None = None
    selection: str | None = None
    require_nonempty: bool = True

    @model_validator(mode="after")
    def required_binding(self):
        if self.kind in {"excitation", "periodic"} and not (self.expected or self.expected_values):
            raise ValueError("Excitation/periodic checks require explicit expected settings.")
        if self.kind == "dataset_binding" and (not self.study or not self.solution):
            raise ValueError("Dataset checks require study and solution.")
        if self.kind == "material_selection" and not self.selection:
            raise ValueError("Material checks require an expected named selection.")
        if self.kind not in {"excitation", "periodic"} and (self.expected or self.expected_values):
            raise ValueError("This check does not support expected settings.")
        if self.kind != "dataset_binding" and (self.study or self.solution or not self.require_nonempty):
            raise ValueError("Only dataset checks support study/solution/require_nonempty.")
        if self.kind != "material_selection" and self.selection:
            raise ValueError("Only material checks support an expected selection.")
        return self


def validate_topics(topics: list[str] | None) -> list[str]:
    selected = list(dict.fromkeys(topics if topics is not None else MODEL_TOPICS))
    unknown = set(selected) - set(MODEL_TOPICS)
    if unknown or not selected:
        raise ValueError(f"Unsupported model topics: {sorted(unknown)}; choose from {MODEL_TOPICS}.")
    return selected


def selected_measurements(profile: dict, ids: list[str] | None = None) -> list[dict]:
    entries = [Measurement.model_validate(item).model_dump(exclude_none=True) for item in profile.get("measurements") or []]
    indexed = {item["id"]: item for item in entries}
    if len(indexed) != len(entries):
        raise ValueError("Duplicate named measurement IDs.")
    if ids is None:
        return entries
    unknown = set(ids) - set(indexed)
    if unknown:
        raise ValueError(f"Unknown named measurements: {sorted(unknown)}")
    return [indexed[name] for name in dict.fromkeys(ids)]
