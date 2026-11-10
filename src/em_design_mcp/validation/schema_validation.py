from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any


# Keywords enforced below. Unknown non-JSON-Schema keys (package annotations
# such as ``unit``) are ignored; JSON Schema validation keywords that are NOT
# implemented are rejected, so a contract never looks stricter than it is.
SUPPORTED_TYPES = ("string", "number", "integer", "boolean", "object", "array", "null")
UNSUPPORTED_KEYWORDS = frozenset({
    "$ref", "$defs", "definitions", "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
    "dependentRequired", "dependentSchemas", "dependencies", "patternProperties", "propertyNames",
    "unevaluatedProperties", "unevaluatedItems", "prefixItems", "additionalItems", "contains",
    "minContains", "maxContains", "minProperties", "maxProperties", "format", "contentEncoding",
    "contentMediaType", "contentSchema",
})


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
    """Validate a candidate; the normalized copy has top-level ``default`` values applied.

    Defaults are applied (and validated) so the values recorded for a run are the
    values the contract advertises, rather than whatever the saved model holds.
    """
    normalized = deepcopy(candidate)
    if not isinstance(schema, dict):
        return False, ["Candidate schema must be an object."], normalized
    if schema.get("type") not in (None, "object"):
        return False, [f"Unsupported schema type: {schema.get('type')!r}"], normalized
    if not isinstance(candidate, dict):
        return False, ["Candidate must be a dictionary."], normalized

    errors = _unsupported(schema, "Candidate schema")
    properties = schema.get("properties", {}) or {}
    if isinstance(properties, dict):
        for name, field_schema in properties.items():
            if name not in normalized and isinstance(field_schema, dict) and "default" in field_schema:
                normalized[name] = deepcopy(field_schema["default"])
    errors.extend(_validate_object(normalized, schema, ""))
    return len(errors) == 0, errors, normalized


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    properties = schema.get("properties", {}) or {}
    if not isinstance(properties, dict):
        return [f"Schema properties for {path or 'the candidate'} must be an object."]
    for field_name in schema.get("required", []) or []:
        if field_name not in value:
            errors.append(f"Missing required field: {_join(path, field_name)}")
    additional = schema.get("additionalProperties", True)
    if additional is False:
        for field_name in sorted(name for name in value if name not in properties):
            errors.append(f"Unexpected field: {_join(path, field_name)}")
    for field_name, field_value in value.items():
        if field_name in properties:
            errors.extend(_validate_value(_join(path, field_name), field_value, properties[field_name]))
        elif isinstance(additional, dict):
            errors.extend(_validate_value(_join(path, field_name), field_value, additional))
    return errors


def _validate_value(name: str, value: Any, field_schema: Any) -> list[str]:
    if not isinstance(field_schema, dict):
        return [f"Schema for field {name} must be an object."]
    errors = _unsupported(field_schema, f"Field {name}")

    declared = field_schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        unknown = [item for item in types if item not in SUPPORTED_TYPES]
        if unknown:
            return errors + [f"Field {name} declares unsupported schema type {unknown!r}."]
        if not any(_matches_type(value, item) for item in types):
            return errors + [_type_message(name, types)]

    if _contains_nonfinite(value):
        return errors + [f"Field {name} must be finite."]

    if "enum" in field_schema:
        enum_values = field_schema["enum"]
        if not isinstance(enum_values, list):
            errors.append(f"Field {name} enum must be a list.")
        elif not any(_json_equal(value, item) for item in enum_values):
            errors.append(f"Field {name} must be one of {enum_values!r}.")
    if "const" in field_schema and not _json_equal(value, field_schema["const"]):
        errors.append(f"Field {name} must equal {field_schema['const']!r}.")

    if _is_number(value):
        exclusive_min = field_schema.get("exclusiveMinimum")
        if exclusive_min is not None and not value > exclusive_min:
            errors.append(f"Field {name} must be > {exclusive_min}.")
        minimum = field_schema.get("minimum")
        if minimum is not None and not value >= minimum:
            errors.append(f"Field {name} must be >= {minimum}.")
        exclusive_max = field_schema.get("exclusiveMaximum")
        if exclusive_max is not None and not value < exclusive_max:
            errors.append(f"Field {name} must be < {exclusive_max}.")
        maximum = field_schema.get("maximum")
        if maximum is not None and not value <= maximum:
            errors.append(f"Field {name} must be <= {maximum}.")
        multiple_of = field_schema.get("multipleOf")
        if multiple_of is not None:
            if not _is_number(multiple_of) or multiple_of <= 0:
                errors.append(f"Field {name} multipleOf must be a positive number.")
            else:
                quotient = value / multiple_of
                if abs(quotient - round(quotient)) > 1e-9 * max(1.0, abs(quotient)):
                    errors.append(f"Field {name} must be a multiple of {multiple_of}.")

    if isinstance(value, str):
        min_length = field_schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"Field {name} must have at least {min_length} characters.")
        max_length = field_schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            errors.append(f"Field {name} must have at most {max_length} characters.")
        pattern = field_schema.get("pattern")
        if pattern is not None:
            try:
                if re.search(str(pattern), value) is None:
                    errors.append(f"Field {name} must match pattern {pattern!r}.")
            except re.error as exc:
                errors.append(f"Field {name} has an invalid pattern {pattern!r}: {exc}.")

    if isinstance(value, list):
        min_items = field_schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"Field {name} must have at least {min_items} items.")
        max_items = field_schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"Field {name} must have at most {max_items} items.")
        if field_schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_json_equal(item, earlier) for earlier in value[:index]):
                    errors.append(f"Field {name} items must be unique.")
                    break
        items = field_schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_value(f"{name}[{index}]", item, items))
        elif items is not None:
            errors.append(f"Field {name} items must be a single schema object.")

    if isinstance(value, dict) and any(key in field_schema for key in ("properties", "required", "additionalProperties")):
        errors.extend(_validate_object(value, field_schema, name))
    return errors


def _unsupported(schema: dict[str, Any], label: str) -> list[str]:
    return [
        f"{label} uses unsupported schema keyword {keyword!r}; it cannot be enforced."
        for keyword in sorted(set(schema) & UNSUPPORTED_KEYWORDS)
    ]


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return _is_number(value)
    if expected == "integer":
        return _is_integer(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return value is None


def _type_message(name: str, types: list[str]) -> str:
    if len(types) == 1:
        article = "an" if types[0][0] in "aeiou" else "a"
        return f"Field {name} must be {article} {types[0]}."
    return f"Field {name} must be one of the types {types!r}."


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality: unlike Python ==, true is not 1 and 1.0 equals 1."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    return type(left) is type(right) and left == right


def _contains_nonfinite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_contains_nonfinite(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_nonfinite(item) for item in value.values())
    return False


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else str(name)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
