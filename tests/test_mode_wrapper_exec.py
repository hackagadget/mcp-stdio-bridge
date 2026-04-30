# SPDX-License-Identifier: Unlicense
import pytest
import sys
import asyncio
from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_handle_call_tool_basic() -> None:
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings
    settings["wrapped_commands"] = [{"name": "echo", "command": ["echo"], "description": "echo"}]
    server = create_wrapper_server()

    mock_result = MagicMock()
    mock_result.stdout = b"hello\n"
    mock_result.returncode = 0

    with patch("anyio.run_process", return_value=mock_result), \
         patch("asyncio.create_subprocess_exec") as mock_exec:

        if sys.platform == "win32":
            mock_p = AsyncMock()
            mock_p.communicate.return_value = (b"hello\n", b"")
            mock_p.returncode = 0
            mock_exec.return_value = mock_p

        result = await server.call_tool_logic("echo", {"subcommand": "hi"})
        assert "hello" in result[0].text


@pytest.mark.anyio
async def test_handle_call_tool_security_patterns() -> None:
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings
    settings["wrapped_commands"] = [
        {
            "name": "safe", "command": "echo", "description": "safe",
            "forbidden_patterns": [r"\.\./"],
            "allowed_patterns": [r"^hello"]
        }
    ]
    server = create_wrapper_server()
    res1 = await server.call_tool_logic("safe", {"subcommand": "bye"})
    assert "not in the allowed list" in res1[0].text
    res2 = await server.call_tool_logic("safe", {"subcommand": "hello ../etc/passwd"})
    assert "restricted security pattern" in res2[0].text
    with patch("anyio.run_process"), patch("asyncio.create_subprocess_exec"):
        res3 = await server.call_tool_logic("safe", {"subcommand": "hello world"})
        assert "not in the allowed list" not in res3[0].text


@pytest.mark.anyio
async def test_handle_call_tool_errors_full() -> None:
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings
    settings["wrapped_commands"] = [{"name": "fail", "command": "false", "description": "fail"}]
    server = create_wrapper_server()
    with pytest.raises(ValueError):
        await server.call_tool_logic("missing", {})
    with patch("anyio.run_process", side_effect=Exception("System Crash")), \
         patch("asyncio.create_subprocess_exec", side_effect=Exception("System Crash")):
        res3 = await server.call_tool_logic("fail", {"subcommand": "hi"})
        assert "System Error" in res3[0].text


@pytest.mark.anyio
async def test_command_string_with_space_is_split() -> None:
    """'command: "wp core"' must produce ["wp", "core", <args>], not ["wp core", <args>]."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [
        {"name": "wp_core", "command": "wp core", "description": "wp core"}
    ]
    server = create_wrapper_server()

    captured: list[list[str]] = []

    async def fake_run_process(cmd: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        captured.append(list(cmd))
        m = MagicMock()
        m.stdout = b"5.9.0"
        return m

    with patch("anyio.run_process", side_effect=fake_run_process), \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        if sys.platform == "win32":
            mock_p = AsyncMock()
            mock_p.communicate.return_value = (b"5.9.0", b"")
            mock_p.returncode = 0
            mock_exec.return_value = mock_p

        await server.call_tool_logic("wp_core", {"subcommand": "version"})

    if sys.platform != "win32":
        assert captured, "run_process was not called"
        assert captured[0] == ["wp", "core", "version"], (
            f"Expected ['wp', 'core', 'version'], got {captured[0]}"
        )


@pytest.mark.anyio
async def test_call_tool_logic_shlex_error() -> None:
    """Unclosed quote in subcommand triggers the shlex exception path (lines 111-112)."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [{"name": "echo", "command": "echo", "description": "echo"}]
    server = create_wrapper_server()

    result = await server.call_tool_logic("echo", {"subcommand": "arg 'unclosed"})
    assert "Error parsing subcommand" in result[0].text


@pytest.mark.anyio
async def test_call_tool_logic_forbidden_args_match() -> None:
    """A subcommand matching forbidden_args is rejected (lines 118-120)."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [
        {"name": "safe", "command": "echo", "description": "safe", "forbidden_args": ["--rm"]}
    ]
    server = create_wrapper_server()

    result = await server.call_tool_logic("safe", {"subcommand": "--rm -rf /"})
    assert "restricted for security" in result[0].text


@pytest.mark.anyio
async def test_call_tool_logic_allowed_args_match() -> None:
    """allowed_args loop is exercised: matching prefix is accepted, non-match is rejected
    (lines 133-135)."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [
        {"name": "safe", "command": "echo", "description": "safe", "allowed_args": ["hello"]}
    ]
    server = create_wrapper_server()

    # "bye" does not start with "hello" → rejected via the allowed_args loop
    result_rejected = await server.call_tool_logic("safe", {"subcommand": "bye"})
    assert "not in the allowed list" in result_rejected[0].text

    # "hello world" starts with "hello" → accepted
    mock_result = MagicMock()
    mock_result.stdout = b"hello world\n"
    mock_result.returncode = 0
    mock_p = AsyncMock()
    mock_p.communicate.return_value = (b"hello world\n", b"")
    mock_p.returncode = 0
    with patch("anyio.run_process", return_value=mock_result), \
         patch("asyncio.create_subprocess_exec", return_value=mock_p):
        result_ok = await server.call_tool_logic("safe", {"subcommand": "hello world"})
    assert "not in the allowed list" not in result_ok[0].text


@pytest.mark.anyio
async def test_call_tool_logic_bare_command_bypasses_allowlist() -> None:
    """Empty subcommand is allowed even when an allowed_args filter is configured."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [
        {"name": "safe", "command": "echo", "description": "safe", "allowed_args": ["hello"]}
    ]
    server = create_wrapper_server()

    mock_result = MagicMock()
    mock_result.stdout = b""
    mock_result.returncode = 0
    mock_p = AsyncMock()
    mock_p.communicate.return_value = (b"", b"")
    mock_p.returncode = 0
    with patch("anyio.run_process", return_value=mock_result), \
         patch("asyncio.create_subprocess_exec", return_value=mock_p):
        result = await server.call_tool_logic("safe", {"subcommand": ""})
    assert "not in the allowed list" not in result[0].text


@pytest.mark.anyio
async def test_call_tool_logic_custom_env() -> None:
    """env dict on a wrapped command is merged into the subprocess environment (line 171)."""
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings

    settings["wrapped_commands"] = [
        {
            "name": "myenv",
            "command": "echo",
            "description": "env test",
            "env": {"MY_CUSTOM_VAR": "hello"},
        }
    ]
    server = create_wrapper_server()

    captured_env: dict[str, str] = {}

    async def fake_run_process(cmd: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        captured_env.update(kwargs.get("env", {}))
        m = MagicMock()
        m.stdout = b"ok"
        return m

    mock_p = AsyncMock()
    mock_p.communicate.return_value = (b"ok", b"")
    mock_p.returncode = 0
    with patch("anyio.run_process", side_effect=fake_run_process), \
         patch("asyncio.create_subprocess_exec", return_value=mock_p):
        await server.call_tool_logic("myenv", {"subcommand": "test"})

    if sys.platform != "win32":
        assert captured_env.get("MY_CUSTOM_VAR") == "hello"


@pytest.mark.anyio
async def test_handle_call_tool_timeout_fix() -> None:
    from mcp_stdio_bridge.mode.wrapper import create_wrapper_server
    from mcp_stdio_bridge.config import settings
    settings["wrapped_commands"] = [{"name": "echo", "command": "echo", "description": "echo",
                                     "timeout": 0.1}]
    server = create_wrapper_server()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        if sys.platform == "win32":
            mock_p = MagicMock()  # Use MagicMock for synchronous methods
            mock_p.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_p.returncode = None
            mock_p.terminate = MagicMock()  # terminate is synchronous
            mock_exec.return_value = mock_p
            result = await server.call_tool_logic("echo", {"subcommand": "hello"})
            assert "timed out" in result[0].text
            assert mock_p.terminate.called
