from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


def deep_merge_schema(base_schema: dict[str, Any], override_schema: dict[str, Any] | None) -> dict[str, Any]:
    if not override_schema:
        return deepcopy(base_schema)

    merged = deepcopy(base_schema)
    for key, value in override_schema.items():
        if key == "required" and isinstance(value, list):
            merged[key] = sorted({*(merged.get(key, []) or []), *value})
            continue
        if key == "properties" and isinstance(value, dict):
            merged.setdefault("properties", {})
            for prop_name, prop_schema in value.items():
                if prop_name in merged["properties"] and isinstance(merged["properties"][prop_name], dict) and isinstance(prop_schema, dict):
                    merged["properties"][prop_name] = deep_merge_schema(merged["properties"][prop_name], prop_schema)
                else:
                    merged["properties"][prop_name] = deepcopy(prop_schema)
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_schema(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def validate_against_schema(candidate: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    normalized = deepcopy(candidate)

    if schema.get("type") not in (None, "object"):
        errors.append(f"Unsupported schema type: {schema.get('type')!r}")
        return False, errors, normalized

    if not isinstance(candidate, dict):
        return False, ["Candidate must be a dictionary."], normalized

    required = schema.get("required", []) or []
    for field_name in required:
        if field_name not in candidate:
            errors.append(f"Missing required field: {field_name}")

    properties = schema.get("properties", {}) or {}
    additional_allowed = schema.get("additionalProperties", True)

    if not additional_allowed:
        unknown_fields = sorted(field_name for field_name in candidate if field_name not in properties)
        for field_name in unknown_fields:
            errors.append(f"Unexpected field: {field_name}")

    for field_name, field_schema in properties.items():
        if field_name not in candidate:
            continue
        value = candidate[field_name]
        ok, field_errors = _validate_schema_value(field_name, value, field_schema)
        if not ok:
            errors.extend(field_errors)

    return len(errors) == 0, errors, normalized


def _validate_schema_value(field_name: str, value: Any, field_schema: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    expected_type = field_schema.get("type")
    if expected_type == "string" and not isinstance(value, str):
        errors.append(f"Field {field_name} must be a string.")
    elif expected_type == "number" and not _is_number(value):
        errors.append(f"Field {field_name} must be a number.")
    elif expected_type == "integer" and not _is_integer(value):
        errors.append(f"Field {field_name} must be an integer.")
    elif expected_type == "object" and not isinstance(value, dict):
        errors.append(f"Field {field_name} must be an object.")
    elif expected_type == "array" and not isinstance(value, list):
        errors.append(f"Field {field_name} must be an array.")

    enum_values = field_schema.get("enum")
    if enum_values is not None and value not in enum_values:
        errors.append(f"Field {field_name} must be one of {enum_values!r}.")

    if _is_number(value):
        if not math.isfinite(float(value)):
            errors.append(f"Field {field_name} must be finite.")
            return False, errors
        exclusive_min = field_schema.get("exclusiveMinimum")
        if exclusive_min is not None and not value > exclusive_min:
            errors.append(f"Field {field_name} must be > {exclusive_min}.")
        minimum = field_schema.get("minimum")
        if minimum is not None and not value >= minimum:
            errors.append(f"Field {field_name} must be >= {minimum}.")
        exclusive_max = field_schema.get("exclusiveMaximum")
        if exclusive_max is not None and not value < exclusive_max:
            errors.append(f"Field {field_name} must be < {exclusive_max}.")
        maximum = field_schema.get("maximum")
        if maximum is not None and not value <= maximum:
            errors.append(f"Field {field_name} must be <= {maximum}.")

    return len(errors) == 0, errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
