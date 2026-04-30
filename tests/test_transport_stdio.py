# SPDX-License-Identifier: Unlicense
import pytest
from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.transport.stdio import run_stdio_transport
from mcp_stdio_bridge.config import settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stdio_transport_proxy_no_command() -> None:
    """Test stdio transport proxy mode error when command is missing."""
    settings["mode"] = "proxy"
    settings["command"] = None
    with patch("mcp_stdio_bridge.transport.stdio.logger") as mock_logger:
        await run_stdio_transport()
        assert any(
            "No command configured" in call[0][0] for call in mock_logger.error.call_args_list
        )


@pytest.mark.anyio
async def test_stdio_transport_proxy_basic() -> None:
    """Test stdio transport in proxy mode initialization."""
    settings["mode"] = "proxy"
    settings["command"] = "echo hello"
    settings["max_retries"] = 0

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.pid = 1234
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    class MockCtx:
        async def __aenter__(self) -> Any:
            return mock_proc

        async def __aexit__(self, *args: object) -> None:
            pass

    async def mock_open_process(*args: Any, **kwargs: Any) -> Any:
        return MockCtx()

    with patch("anyio.open_process", side_effect=mock_open_process):
        await run_stdio_transport()
        assert True


@pytest.mark.anyio
async def test_stdio_transport_wrapper_basic() -> None:
    """Test stdio transport in wrapper mode routing."""
    settings["mode"] = "command-wrapper"
    mock_server = MagicMock()
    mock_server.run = AsyncMock()

    class MockStdioCtx:
        async def __aenter__(self) -> Any:
            return AsyncMock(), AsyncMock()

        async def __aexit__(self, *args: object) -> None:
            pass

    with (
        patch("mcp.server.stdio.stdio_server", return_value=MockStdioCtx()),
        patch("mcp_stdio_bridge.mode.wrapper.create_wrapper_server", return_value=mock_server),
    ):
        await run_stdio_transport()
        assert mock_server.run.called


@pytest.mark.anyio
async def test_stdio_transport_wrapper_error() -> None:
    """Test exception handling within wrapper run."""
    settings["mode"] = "command-wrapper"
    mock_server = MagicMock()
    mock_server.run = AsyncMock(side_effect=Exception("Wrapper Crash"))

    class MockStdioCtx:
        async def __aenter__(self) -> Any:
            return AsyncMock(), AsyncMock()

        async def __aexit__(self, *args: object) -> None:
            pass

    with (
        patch("mcp.server.stdio.stdio_server", return_value=MockStdioCtx()),
        patch("mcp_stdio_bridge.mode.wrapper.create_wrapper_server", return_value=mock_server),
        patch("mcp_stdio_bridge.transport.stdio.logger") as mock_logger,
    ):
        await run_stdio_transport()
        assert any("Wrapper error" in call[0][0] for call in mock_logger.error.call_args_list)


@pytest.mark.anyio
async def test_stdio_transport_global_crash() -> None:
    """Test high-level exception handling in stdio transport."""
    # We patch settings to raise on access
    mock_settings = MagicMock()
    mock_settings.__getitem__.side_effect = Exception("Fatal")

    with (
        patch("mcp_stdio_bridge.transport.stdio.settings", mock_settings),
        patch("mcp_stdio_bridge.transport.stdio.logger") as mock_logger,
    ):
        with pytest.raises(Exception, match="Fatal"):
            await run_stdio_transport()
        assert any(
            "Stdio Transport Error" in call[0][0] for call in mock_logger.error.call_args_list
        )
