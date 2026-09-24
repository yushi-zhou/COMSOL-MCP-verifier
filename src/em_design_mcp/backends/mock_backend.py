from __future__ import annotations

from hashlib import sha256
from typing import Any


class MockBackend:
    def run(
        self,
        *,
        model_profile: dict[str, Any],
        problem_spec: dict[str, Any],
        candidate: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        output_schema = model_profile.get("output_schema", {}) or {}
        if "data_by_lam" in (output_schema.get("required", []) or []) or "data_by_lam" in (output_schema.get("properties", {}) or {}):
            return self._build_data_by_lam_output(problem_spec, model_profile, candidate, run_id)
        return self._build_generic_output(problem_spec, candidate, run_id)

    def _build_data_by_lam_output(self, problem_spec: dict[str, Any], model_profile: dict[str, Any], candidate: dict[str, Any], run_id: str) -> dict[str, Any]:
        wavelengths = problem_spec.get("independent_variables", {}).get("wavelength_nm") or []
        data_by_lam: dict[str, dict[str, list[float]]] = {}
        base = self._seed_value(candidate, run_id)
        sweep_points = self._sweep_points(candidate, model_profile)

        for index, wavelength in enumerate(wavelengths):
            param_nm = sweep_points
            t_values = [self._bounded_value(base, wavelength, point, index, point_index) for point_index, point in enumerate(param_nm)]
            phi_values = [self._phase_value(base, wavelength, point, index, point_index, len(param_nm)) for point_index, point in enumerate(param_nm)]
            data_by_lam[str(wavelength)] = {
                "param_nm": param_nm,
                "T": t_values,
                "phi_rad": phi_values,
            }

        return {
            "data_by_lam": data_by_lam,
            "summary_metrics": {
                "mean_transmission": sum(sum(values["T"]) for values in data_by_lam.values()) / max(1, sum(len(values["T"]) for values in data_by_lam.values())),
                "phase_coverage_hint": 6.283185307179586,
            },
            "artifacts": {
                "run_id": run_id,
            },
        }

    def _build_generic_output(self, problem_spec: dict[str, Any], candidate: dict[str, Any], run_id: str) -> dict[str, Any]:
        seed = self._seed_value(candidate, run_id)
        frequency_count = len(problem_spec.get("independent_variables", {}).get("frequency_hz") or [])
        score = 0.7 + (seed % 17) / 100.0
        mean_transmission = 0.6 + (seed % 11) / 100.0
        return {
            "summary_metrics": {
                "score": score,
                "mean_transmission": mean_transmission,
                "sample_count": frequency_count or 1,
            },
            "artifacts": {
                "run_id": run_id,
            },
        }

    @staticmethod
    def _seed_value(candidate: dict[str, Any], run_id: str) -> int:
        digest = sha256(_stable_payload(candidate, run_id).encode("utf-8")).hexdigest()
        return int(digest[:12], 16)

    def _sweep_points(self, candidate: dict[str, Any], model_profile: dict[str, Any]) -> list[float]:
        sweep_config = ((model_profile.get("mock_generation") or {}).get("sweep") or {})
        if sweep_config:
            start = self._resolve_numeric_field(candidate, sweep_config.get("start_field"), sweep_config.get("default_start", 0.0))
            stop_default = float(sweep_config.get("default_stop_offset", 10.0))
            stop = self._resolve_numeric_field(candidate, sweep_config.get("stop_field"), start + stop_default)
            if stop <= start:
                stop = start + stop_default
            max_points = max(2, int(sweep_config.get("max_points", 7)))
            return self._build_linear_points(start, stop, max_points)

        numeric_values = [float(value) for value in candidate.values() if isinstance(value, (int, float))]
        if len(numeric_values) >= 2:
            start = min(numeric_values)
            stop = max(numeric_values)
            if stop <= start:
                stop = start + 10.0
            return self._build_linear_points(start, stop, 5)

        return self._build_linear_points(0.0, 10.0, 5)

    @staticmethod
    def _bounded_value(seed: int, wavelength: Any, point: float, wavelength_index: int, point_index: int) -> float:
        base = (seed % 1000) / 1000.0
        wobble = _stable_int(seed, wavelength, point, wavelength_index, point_index, modulus=37)
        centered = (wobble - 18) / 100.0
        value = 0.8 + 0.05 * base + 0.02 * centered
        return max(0.0, min(0.999, round(value, 6)))

    @staticmethod
    def _phase_value(seed: int, wavelength: Any, point: float, wavelength_index: int, point_index: int, total_points: int) -> float:
        start = _stable_int(seed, wavelength, "phase-start", wavelength_index, modulus=628) / 100.0
        span = 2.2 * 3.141592653589793
        step = span / max(1, total_points - 1)
        wobble = _stable_int(seed, wavelength, point, wavelength_index, point_index, "phase-wobble", modulus=9)
        return round(start + step * point_index + wobble / 1000.0, 6)

    @staticmethod
    def _resolve_numeric_field(candidate: dict[str, Any], field_name: Any, default_value: float) -> float:
        if isinstance(field_name, str) and field_name in candidate and isinstance(candidate[field_name], (int, float)):
            return float(candidate[field_name])
        return float(default_value)

    @staticmethod
    def _build_linear_points(start: float, stop: float, max_points: int) -> list[float]:
        if max_points < 2:
            max_points = 2
        if stop <= start:
            stop = start + 10.0
        step = (stop - start) / max(1, max_points - 1)
        points = [round(start + step * index, 6) for index in range(max_points)]
        points[0] = round(start, 6)
        points[-1] = round(stop, 6)
        return points


def _stable_payload(candidate: dict[str, Any], run_id: str) -> str:
    candidate_parts = [f"{key}={candidate[key]!r}" for key in sorted(candidate)]
    return f"run_id={run_id}|" + "|".join(candidate_parts)


def _stable_int(*parts: Any, modulus: int) -> int:
    payload = "|".join(repr(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulus
