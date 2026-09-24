from __future__ import annotations

from .base import BackendConfigurationError
from .matlab_livelink_backend import MatlabLiveLinkBackend
from .mock_backend import MockBackend


SUPPORTED_BACKENDS = {"mock", "matlab_livelink"}


def create_backend(backend: str, *, timeout_seconds: int | None = None, parser_registry=None):
    backend_name = str(backend).strip()
    if backend_name == "mock":
        return MockBackend()
    if backend_name == "matlab_livelink":
        return MatlabLiveLinkBackend(
            timeout_seconds=timeout_seconds or 3600,
            parser_registry=parser_registry,
        )
    raise BackendConfigurationError(f"Unsupported backend: {backend_name!r}")


def is_supported_backend(backend: str) -> bool:
    return str(backend).strip() in SUPPORTED_BACKENDS
