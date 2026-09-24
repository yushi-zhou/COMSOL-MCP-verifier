from __future__ import annotations

from em_design_mcp.server import create_server


def test_public_mcp_surface_is_seven_agent_tools() -> None:
    server = create_server()
    assert set(server._tool_manager._tools) == {
        "discover_designs",
        "inspect_contract",
        "inspect_model",
        "prepare_run",
        "start_run",
        "get_run",
        "cancel_run",
    }
