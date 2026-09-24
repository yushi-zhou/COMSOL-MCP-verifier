"""Agent-first, contract-bounded COMSOL execution service."""

__all__ = ["create_server"]


def __getattr__(name: str):
    if name == "create_server":
        from .server import create_server

        return create_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
