# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from unittest.mock import AsyncMock, patch, MagicMock
from mcp_stdio_bridge.config import settings
from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
import mcp.types as types

@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'

@pytest.mark.anyio
async def test_wrapper_forbidden_args() -> None:
    """Test that forbidden argument prefixes are blocked."""
    settings["wrapped_commands"] = [{
        "name": "test_tool",
        "description": "A test tool",
        "command": "echo",
        "forbidden_args": ["forbidden", "secret"]
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Try a forbidden command
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="test_tool",
                                           arguments={"subcommand": "forbidden command"})
    )
    result = await handler(req)
    assert "restricted" in result.root.content[0].text

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="test_tool",
                                           arguments={"subcommand": "SECRET data"})
    )
    result = await handler(req)
    assert "restricted" in result.root.content[0].text

    # Try a safe command
    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"safe output"
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="test_tool",
                                               arguments={"subcommand": "safe command"})
        )
        result = await handler(req)
        assert result.root.content[0].text == "safe output"
        mock_run.assert_called_once()
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_forbidden_patterns() -> None:
    """Test that forbidden regex patterns are blocked."""
    settings["wrapped_commands"] = [{
        "name": "regex_tool",
        "description": "desc",
        "command": "echo",
        "forbidden_patterns": ["^db.*drop$", "secret-.*"]
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Try forbidden patterns
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="regex_tool",
                                           arguments={"subcommand": "db drop"})
    )
    result = await handler(req)
    assert "restricted security pattern" in result.root.content[0].text

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="regex_tool",
                                           arguments={"subcommand": "use secret-key-1"})
    )
    result = await handler(req)
    assert "restricted security pattern" in result.root.content[0].text

@pytest.mark.anyio
async def test_wrapper_allowed_args() -> None:
    """Test that only allowed argument prefixes are permitted."""
    settings["wrapped_commands"] = [{
        "name": "allowed_tool",
        "description": "desc",
        "command": "echo",
        "allowed_args": ["status", "list"]
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Try an unauthorized command
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="allowed_tool",
                                           arguments={"subcommand": "delete all"})
    )
    result = await handler(req)
    assert "not in the allowed list" in result.root.content[0].text

    # Try an authorized command
    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"status ok"
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="allowed_tool",
                                               arguments={"subcommand": "STATUS verbose"})
        )
        result = await handler(req)
        assert result.root.content[0].text == "status ok"
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_allowed_patterns() -> None:
    """Test that only allowed regex patterns are permitted."""
    settings["wrapped_commands"] = [{
        "name": "allowed_regex",
        "description": "desc",
        "command": "echo",
        "allowed_patterns": ["^get-.*", "^list-.*"]
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Unauthorized
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="allowed_regex",
                                           arguments={"subcommand": "set-value 10"})
    )
    result = await handler(req)
    assert "not in the allowed list" in result.root.content[0].text

    # Authorized
    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"got data"
        mock_run.return_value = mock_result
        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="allowed_regex",
                                               arguments={"subcommand": "get-info --id 5"})
        )
        result = await handler(req)
        assert result.root.content[0].text == "got data"

@pytest.mark.anyio
async def test_wrapper_mutual_exclusivity() -> None:
    """Test that a tool with both allowed and forbidden rules is skipped."""
    settings["wrapped_commands"] = [{
        "name": "invalid_tool",
        "description": "desc",
        "command": "echo",
        "forbidden_args": ["f"],
        "allowed_patterns": [".*"]
    }]

    with patch("mcp_stdio_bridge.mode.wrapper.logger.error") as mock_error:
        server = create_wrapper_server()
        # Trigger validation via handler
        await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())
        mock_error.assert_called_with("Command 'invalid_tool' has both allowed_args and "
                                      "forbidden_args security rules. Skipping.")
        # Ensure it's NOT in the tool list by checking the registered handler
        handler = server.request_handlers[types.ListToolsRequest]
        tools_result = await handler(types.ListToolsRequest())
        # tools_result.root is a ListToolsResult object containing a 'tools' list
        tool_names = [t.name for t in tools_result.root.tools]
        assert "invalid_tool" not in tool_names

@pytest.mark.anyio
async def test_wrapper_allowed_args_with_forbidden_patterns() -> None:
    """Test that forbidden_patterns veto commands even when allowed_args passes,
    and that combining the two is valid (tool is not skipped)."""
    settings["wrapped_commands"] = [{
        "name": "combo_tool",
        "description": "desc",
        "command": "wp",
        "allowed_args": ["plugin list", "plugin status"],
        "forbidden_patterns": ["--exec", "--require"]
    }]

    server = create_wrapper_server()

    # Tool must be registered — allowed_args + forbidden_patterns is now a valid combination.
    tools_result = await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())
    assert "combo_tool" in [t.name for t in tools_result.root.tools]

    handler = server.request_handlers[types.CallToolRequest]

    # Rejected by allowlist (prefix not permitted).
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="combo_tool",
                                           arguments={"subcommand": "plugin delete my-plugin"})
    )
    result = await handler(req)
    assert "not in the allowed list" in result.root.content[0].text

    # Passes allowlist but vetoed by forbidden_patterns as a final check.
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="combo_tool",
                                           arguments={"subcommand": "plugin list --exec=phpinfo()"})
    )
    result = await handler(req)
    assert "restricted security pattern" in result.root.content[0].text

    # Passes both checks — executes normally.
    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"plugin output"
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(
                name="combo_tool",
                arguments={"subcommand": "plugin list --format=json"}
            )
        )
        result = await handler(req)
        assert result.root.content[0].text == "plugin output"
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_execution_timeout() -> None:
    """Test that command timeouts are handled."""
    settings["wrapped_commands"] = [{
        "name": "slow_tool",
        "description": "A slow tool",
        "command": "sleep",
        "timeout": 1
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process", new_callable=AsyncMock,
               side_effect=TimeoutError()):
        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="slow_tool",
                                               arguments={"subcommand": "10"})
        )
        result = await handler(req)
        assert "timed out" in result.root.content[0].text
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_execution_error() -> None:
    """Test that execution errors are captured."""
    settings["wrapped_commands"] = [{
        "name": "fail_tool",
        "description": "A failing tool",
        "command": "false"
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"error message"
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="fail_tool",
                                               arguments={"subcommand": ""})
        )
        result = await handler(req)
        assert result.root.content[0].text == "error message"
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_unknown_tool() -> None:
    """Test behavior when an unknown tool is called."""
    settings["wrapped_commands"] = []
    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="ghost_tool", arguments={"subcommand": ""})
    )
    try:
        await handler(req)
    except ValueError as e:
        assert "Unknown tool" in str(e)
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_invalid_subcommand() -> None:
    """Test behavior with malformed subcommand string."""
    settings["wrapped_commands"] = [{
        "name": "tool",
        "description": "desc",
        "command": "echo"
    }]
    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Unclosed quote is an invalid subcommand for shlex
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="tool",
                                           arguments={"subcommand": 'missing quote"'})
    )
    result = await handler(req)
    assert "Error parsing subcommand" in result.root.content[0].text
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_large_output() -> None:
    """Test that wrapper handles large stdout volumes."""
    settings["wrapped_commands"] = [{
        "name": "big_tool",
        "description": "desc",
        "command": "cat"
    }]
    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    large_data = b"x" * 1000000 # 1MB

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = large_data
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="big_tool",
                                               arguments={"subcommand": "file"})
        )
        result = await handler(req)
        assert len(result.root.content[0].text) == 1000000
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_empty_output_actual() -> None:
    """Test that wrapper handles empty stdout correctly (line 112)."""
    settings["wrapped_commands"] = [{
        "name": "empty_tool",
        "description": "desc",
        "command": "echo"
    }]
    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"" # EMPTY
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="empty_tool",
                                               arguments={"subcommand": ""})
        )
        result = await handler(req)
        assert "executed successfully" in result.root.content[0].text
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_wrapper_custom_env() -> None:
    """Test that tool-specific environment variables are passed correctly."""
    settings["wrapped_commands"] = [{
        "name": "env_tool",
        "description": "desc",
        "command": "env",
        "env": {"TEST_VAR": "passed"}
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = b"TEST_VAR=passed"
        mock_run.return_value = mock_result

        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="env_tool",
                                               arguments={"subcommand": ""})
        )
        await handler(req)

        # Verify that the env passed to run_process contains the custom variable
        passed_env = mock_run.call_args.kwargs["env"]
        assert passed_env["TEST_VAR"] == "passed"

@pytest.mark.anyio
async def test_wrapper_path_sanitization() -> None:
    """Test that path traversal attempts are blocked when cwd is set."""
    import sys
    cwd = "C:/safe/dir" if sys.platform == "win32" else "/safe/dir"
    unauthorized = "C:/windows/system32" if sys.platform == "win32" else "/usr/bin"

    settings["wrapped_commands"] = [{
        "name": "path_tool",
        "description": "desc",
        "command": "ls",
        "cwd": cwd,
    }]

    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    # Try directory traversal
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="path_tool",
                                           arguments={"subcommand": "../../etc/passwd"})
    )
    result = await handler(req)
    assert "Path traversal" in result.root.content[0].text

    # Try unauthorized absolute path
    req = types.CallToolRequest(
        params=types.CallToolRequestParams(name="path_tool",
                                           arguments={"subcommand": unauthorized})
    )
    result = await handler(req)
    assert "Path traversal" in result.root.content[0].text

@pytest.mark.anyio
async def test_wrapper_system_error_actual() -> None:
    """Test that wrapper handles unexpected system errors (lines 118-120)."""
    settings["wrapped_commands"] = [{
        "name": "fail_tool",
        "description": "desc",
        "command": "echo"
    }]
    server = create_wrapper_server()
    handler = server.request_handlers[types.CallToolRequest]

    with patch("mcp_stdio_bridge.mode.wrapper.anyio.run_process",
               new_callable=AsyncMock, side_effect=RuntimeError("Crash")):
        req = types.CallToolRequest(
            params=types.CallToolRequestParams(name="fail_tool",
                                               arguments={"subcommand": ""})
        )
        result = await handler(req)
        assert "System Error" in result.root.content[0].text
    await anyio.lowlevel.checkpoint()
