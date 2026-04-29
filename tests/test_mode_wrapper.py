# SPDX-License-Identifier: Unlicense
import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_apply_groups() -> None:
    from mcp_stdio_bridge.mode.wrapper import apply_groups

    cmd_config = {"name": "test", "command": "ls", "apply": ["g1"]}
    groups = {"g1": {"forbidden_args": ["-la"]}}

    effective = apply_groups(cmd_config, groups)
    assert effective["forbidden_args"] == ["-la"]


def test_apply_groups_unknown_group_skipped() -> None:
    """Unknown group name triggers the continue branch (line 31) and is silently skipped."""
    from mcp_stdio_bridge.mode.wrapper import apply_groups

    cmd_config = {"name": "test", "command": "ls", "apply": ["unknown_group", "g1"]}
    groups = {"g1": {"forbidden_args": ["-la"]}}

    effective = apply_groups(cmd_config, groups)
    assert effective["forbidden_args"] == ["-la"]


def test_apply_groups_scalar_field_from_group() -> None:
    """A scalar field (e.g. timeout) in a group is assigned via line 40."""
    from mcp_stdio_bridge.mode.wrapper import apply_groups

    cmd_config = {"name": "test", "command": "ls", "apply": ["g1"]}
    groups = {"g1": {"timeout": 120}}

    effective = apply_groups(cmd_config, groups)
    assert effective["timeout"] == 120


def test_apply_groups_cmd_config_list_fields_merged() -> None:
    """cmd_config list fields are merged with group list fields (lines 45, 49)."""
    from mcp_stdio_bridge.mode.wrapper import apply_groups

    cmd_config = {"name": "test", "command": "ls", "apply": ["g1"], "forbidden_args": ["-rf"]}
    groups = {"g1": {"forbidden_args": ["-la"]}}

    effective = apply_groups(cmd_config, groups)
    assert "-la" in effective["forbidden_args"]
    assert "-rf" in effective["forbidden_args"]


@pytest.mark.anyio
async def test_wrapper_server_creation() -> None:
    """Test that the wrapper server initializes with tools."""
    # Lazy imports inside the test to ensure conftest patches are active
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [{"name": "echo", "command": "echo", "description": "echo test"}]

    server = create_wrapper_server()
    assert server is not None

    # We verify the tools by triggering the internal request handler map.
    # In the MCP SDK, we can look up the handler by name.
    # We just need to find which function belongs to "tools/list".

    # Verify we can list tools
    tools = await server.get_tools()  # This is a helper we'll add to mode/wrapper.py
    assert any(t.name == "echo" for t in tools)
