# SPDX-License-Identifier: Unlicense
import pytest
from mcp_stdio_bridge.config import settings
import mcp.types as types

@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'

@pytest.mark.anyio
async def test_wrapper_server_dynamic_tools() -> None:
    """Test that wrapper server picks up tool changes without re-initialization."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    
    settings["wrapped_commands"] = [{"name": "tool1", "command": "echo", "description": "d1"}]
    server = create_wrapper_server()
    
    # List tools - in v1.0.0 of SDK it is request_handlers
    handler = server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest())
    # The result is wrapped in a root object in some SDK versions
    tools = result.root.tools if hasattr(result, 'root') else result.tools
    assert len(tools) == 1
    assert tools[0].name == "tool1"
    
    # Change settings
    settings["wrapped_commands"] = [
        {"name": "tool1", "command": "echo", "description": "d1"},
        {"name": "tool2", "command": "ls", "description": "d2"}
    ]
    
    # List tools again (handler should see new settings)
    result2 = await handler(types.ListToolsRequest())
    tools2 = result2.root.tools if hasattr(result2, 'root') else result2.tools
    assert len(tools2) == 2
    assert tools2[1].name == "tool2"
