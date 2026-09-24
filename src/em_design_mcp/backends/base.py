from __future__ import annotations

from typing import Any, Protocol


class Backend(Protocol):
    def run(self, *, model_profile: dict[str, Any], problem_spec: dict[str, Any], candidate: dict[str, Any], run_id: str) -> dict[str, Any]:
        ...


class BackendError(RuntimeError):
    def __init__(self, message: str, *, failure_category: str = "unknown_failure", warnings: list[str] | None = None):
        super().__init__(message)
        self.failure_category = failure_category
        self.warnings = warnings or []


class BackendConfigurationError(BackendError):
    def __init__(self, message: str, *, warnings: list[str] | None = None):
        super().__init__(message, failure_category="model_profile_incompatible", warnings=warnings)


class BackendExecutionError(BackendError):
    def __init__(self, message: str, *, failure_category: str = "backend_execution_error", warnings: list[str] | None = None):
        super().__init__(message, failure_category=failure_category, warnings=warnings)
