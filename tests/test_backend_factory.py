from __future__ import annotations

import pytest

from em_design_mcp.backends.backend_factory import create_backend
from em_design_mcp.backends.base import BackendConfigurationError
from em_design_mcp.backends.matlab_livelink_backend import MatlabLiveLinkBackend
from em_design_mcp.backends.mock_backend import MockBackend


def test_backend_factory_creates_mock_backend() -> None:
    assert isinstance(create_backend("mock"), MockBackend)


def test_backend_factory_creates_matlab_livelink_backend() -> None:
    assert isinstance(create_backend("matlab_livelink"), MatlabLiveLinkBackend)


def test_backend_factory_passes_timeout_to_matlab_livelink_backend() -> None:
    backend = create_backend("matlab_livelink", timeout_seconds=17)
    assert isinstance(backend, MatlabLiveLinkBackend)
    assert backend._timeout_seconds == 17


def test_backend_factory_rejects_unknown_backend() -> None:
    with pytest.raises(BackendConfigurationError, match="Unsupported backend"):
        create_backend("not_a_backend")
