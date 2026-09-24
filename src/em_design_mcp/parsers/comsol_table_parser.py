from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
from typing import Any


DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM = 1e-3


def parse_comsol_table_file(
    path: str | Path,
    *,
    wavelengths_nm: list[Any] | None = None,
    wavelength_match_tolerance_nm: float = DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM,
) -> dict[str, Any]:
    return parse_comsol_table_text(
        Path(path).read_text(encoding="utf-8-sig"),
        wavelengths_nm=wavelengths_nm,
        wavelength_match_tolerance_nm=wavelength_match_tolerance_nm,
    )


def parse_comsol_table_text(
    text: str,
    *,
    wavelengths_nm: list[Any] | None = None,
    wavelength_match_tolerance_nm: float = DEFAULT_WAVELENGTH_MATCH_TOLERANCE_NM,
) -> dict[str, Any]:
    rows = _read_numeric_rows(text)
    if not rows:
        raise ValueError("No numeric COMSOL table rows found.")

    targets = [_coerce_float(value) for value in (wavelengths_nm or [])]
    tolerance_nm = _coerce_tolerance(wavelength_match_tolerance_nm)
    grouped: dict[str, list[tuple[float, float, float]]] = defaultdict(list)

    for row in rows:
        if len(row) >= 5:
            param_nm = row[0]
            wavelength = _snap_wavelength(row[1], targets, tolerance_nm=tolerance_nm)
            transmission = row[3]
            phase_rad = row[4]
        elif len(row) >= 4 and len(targets) == 1:
            param_nm = row[0]
            wavelength = targets[0]
            transmission = row[2]
            phase_rad = row[3]
        else:
            continue
        grouped[_format_wavelength_key(wavelength)].append((param_nm, transmission, phase_rad))

    if not grouped:
        raise ValueError("No supported COMSOL table rows found.")

    data_by_lam: dict[str, dict[str, list[float]]] = {}
    for wavelength_key, series in grouped.items():
        ordered = sorted(series, key=lambda item: item[0])
        data_by_lam[wavelength_key] = {
            "param_nm": [_clean_float(item[0]) for item in ordered],
            "T": [_clean_float(item[1]) for item in ordered],
            "phi_rad": [_clean_float(item[2]) for item in ordered],
        }

    return {
        "data_by_lam": data_by_lam,
        "summary_metrics": {
            "mean_transmission": _mean_transmission(data_by_lam),
        },
    }


def _read_numeric_rows(text: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        numeric_parts: list[float] = []
        for part in parts:
            try:
                numeric_parts.append(float(part))
            except ValueError:
                numeric_parts = []
                break
        if numeric_parts:
            rows.append(numeric_parts)
    return rows


def _snap_wavelength(value: float, targets: list[float], *, tolerance_nm: float) -> float:
    if not targets:
        return value
    nearest = min(targets, key=lambda target: abs(target - value))
    distance_nm = abs(nearest - value)
    if distance_nm > tolerance_nm:
        raise ValueError(
            f"COMSOL table wavelength {value:g} nm is {distance_nm:g} nm from nearest expected "
            f"wavelength {nearest:g} nm, exceeding tolerance {tolerance_nm:g} nm."
        )
    return nearest


def _format_wavelength_key(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _mean_transmission(data_by_lam: dict[str, dict[str, list[float]]]) -> float:
    values = [value for series in data_by_lam.values() for value in series.get("T", [])]
    return sum(values) / len(values) if values else 0.0


def _coerce_float(value: Any) -> float:
    return float(str(value).strip().lower().replace("nm", ""))


def _coerce_tolerance(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("wavelength_match_tolerance_nm must be a finite non-negative number.")
    try:
        tolerance = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("wavelength_match_tolerance_nm must be a finite non-negative number.") from exc
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("wavelength_match_tolerance_nm must be a finite non-negative number.")
    return tolerance


def _clean_float(value: float) -> float:
    return int(value) if float(value).is_integer() else float(value)
