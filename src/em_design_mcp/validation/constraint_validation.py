from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstraintCheckResult:
    valid: bool
    errors: list[str]
    warnings: list[str]


def validate_constraints(candidate: dict[str, Any], constraints: list[dict[str, Any]]) -> ConstraintCheckResult:
    errors: list[str] = []
    warnings: list[str] = []

    for constraint in constraints:
        constraint_id = str(constraint.get("constraint_id", "unknown_constraint"))
        constraint_type = constraint.get("type")
        if constraint_type != "field_comparison":
            errors.append(f"Constraint {constraint_id}: unsupported type {constraint_type!r}; cannot validate.")
            continue

        ok, message = _check_field_comparison(candidate, constraint)
        if not ok:
            errors.append(f"{constraint_id}: {message}")

    return ConstraintCheckResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _check_field_comparison(candidate: dict[str, Any], constraint: dict[str, Any]) -> tuple[bool, str]:
    left = constraint.get("left") or {}
    right = constraint.get("right") or {}
    operator = constraint.get("operator")
    message = str(constraint.get("message") or "Constraint failed.")

    left_value, left_error = _resolve_operand(candidate, left)
    if left_error:
        return False, left_error
    right_value, right_error = _resolve_operand(candidate, right)
    if right_error:
        return False, right_error

    try:
        if operator == ">":
            ok = left_value > right_value
        elif operator == ">=":
            ok = left_value >= right_value
        elif operator == "<":
            ok = left_value < right_value
        elif operator == "<=":
            ok = left_value <= right_value
        elif operator == "==":
            ok = left_value == right_value
        elif operator == "in":
            ok = left_value in right_value
        else:
            return False, f"Unsupported operator {operator!r}."
    except (TypeError, ValueError):
        return False, f"Constraint operands are not comparable for operator {operator!r}."

    if not ok:
        return False, message
    return True, ""


def _resolve_operand(candidate: dict[str, Any], operand: Any) -> tuple[Any, str | None]:
    if isinstance(operand, dict):
        if "field" in operand:
            field_name = operand["field"]
            if field_name not in candidate:
                return None, f"Missing field {field_name!r} required by constraint."
            value = candidate[field_name]
            offset = operand.get("offset", 0)
            if offset and isinstance(value, (int, float)):
                return value + offset, None
            if offset and not isinstance(value, (int, float)):
                return None, f"Field {field_name!r} does not support numeric offsets."
            return value, None
        if "const" in operand:
            return operand["const"], None
    return operand, None
