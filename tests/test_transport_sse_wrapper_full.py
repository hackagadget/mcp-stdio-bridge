# SPDX-License-Identifier: Unlicense
import pytest
from starlette.responses import Response
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.transport.sse_wrapper import (
    handle_sse,
    refresh_wrapper_server,
    get_wrapper_app,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_get_wrapper_app_caching() -> None:
    refresh_wrapper_server()
    app1 = get_wrapper_app()
    app2 = get_wrapper_app()
    assert app1 is app2


@pytest.mark.anyio
async def test_handle_sse_success() -> None:
    refresh_wrapper_server()
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"
    mock_request.scope = {"type": "http"}
    mock_request.receive = AsyncMock()
    mock_request._send = AsyncMock()

    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()

    mock_server = MagicMock()
    mock_server.run = AsyncMock()
    mock_server.create_initialization_options = MagicMock()

    get_wrapper_app()
    from mcp_stdio_bridge.transport import sse_wrapper

    with (
        patch.object(sse_wrapper._sse_transport, "connect_sse") as mock_connect,
        patch(
            "mcp_stdio_bridge.transport.sse_wrapper.create_wrapper_server", return_value=mock_server
        ),
    ):
        mock_connect.return_value.__aenter__.return_value = (mock_sse_read, mock_sse_write)
        resp = await handle_sse(mock_request)
        assert mock_server.run.called
        assert isinstance(resp, Response)


@pytest.mark.anyio
async def test_handle_sse_wrapper_error() -> None:
    refresh_wrapper_server()
    mock_request = MagicMock()
    mock_request.headers = {"X-Forwarded-For": "1.2.3.4"}
    mock_request.scope = {"type": "http"}
    mock_request.receive = AsyncMock()
    mock_request._send = AsyncMock()

    mock_server = MagicMock()
    mock_server.run = AsyncMock(side_effect=Exception("Wrapper Failed"))

    get_wrapper_app()
    from mcp_stdio_bridge.transport import sse_wrapper

    with (
        patch.object(sse_wrapper._sse_transport, "connect_sse") as mock_connect,
        patch(
            "mcp_stdio_bridge.transport.sse_wrapper.create_wrapper_server", return_value=mock_server
        ),
        patch("mcp_stdio_bridge.transport.sse_wrapper.logger") as mock_logger,
    ):
        mock_connect.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        resp = await handle_sse(mock_request)
        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
        assert any("Wrapper error" in msg for msg in error_calls)
        assert isinstance(resp, Response)


@pytest.mark.anyio
async def test_handle_sse_crash() -> None:
    refresh_wrapper_server()
    mock_request = MagicMock()
    mock_request.headers = MagicMock()
    mock_request.headers.get.side_effect = Exception("Header Crash")

    with patch("mcp_stdio_bridge.transport.sse_wrapper.logger") as mock_logger:
        resp = await handle_sse(mock_request)
        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
        assert any("SSE Handler crash" in msg for msg in error_calls)
        assert isinstance(resp, Response)


@pytest.mark.anyio
async def test_handle_sse_cancel_path() -> None:
    refresh_wrapper_server()
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"
    mock_request.scope = {"type": "http"}
    mock_request.receive = AsyncMock()
    mock_request._send = AsyncMock()

    mock_server = MagicMock()
    mock_server.run = AsyncMock()

    get_wrapper_app()
    from mcp_stdio_bridge.transport import sse_wrapper

    with (
        patch.object(sse_wrapper._sse_transport, "connect_sse") as mock_connect,
        patch(
            "mcp_stdio_bridge.transport.sse_wrapper.create_wrapper_server", return_value=mock_server
        ),
        patch("mcp_stdio_bridge.transport.sse_wrapper.ActivityMonitor") as mock_monitor_cls,
    ):
        mock_monitor = MagicMock()
        # Ensure watcher is a real coroutine function or a mock that returns a coroutine
        mock_monitor.watcher = AsyncMock()
        mock_monitor_cls.return_value = mock_monitor

        mock_connect.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        await handle_sse(mock_request)
        assert mock_server.run.called


@pytest.mark.anyio
async def test_run_wrapper_transport() -> None:
    """run_wrapper_transport configures Uvicorn and calls server.serve() (lines 107-120)."""
    from mcp_stdio_bridge.transport.sse_wrapper import run_wrapper_transport
    from mcp_stdio_bridge.config import settings

    settings["host"] = "127.0.0.1"
    settings["port"] = 8000
    settings["logging_level"] = "INFO"

    mock_server = MagicMock()
    mock_server.serve = AsyncMock()

    with (
        patch("mcp_stdio_bridge.transport.sse_wrapper.uvicorn.Config"),
        patch("mcp_stdio_bridge.transport.sse_wrapper.uvicorn.Server", return_value=mock_server),
        patch("mcp_stdio_bridge.transport.sse_wrapper.get_wrapper_app"),
    ):
        await run_wrapper_transport()

    mock_server.serve.assert_called_once()


def test_refresh_wrapper_server_logic() -> None:
    from mcp_stdio_bridge.transport import sse_wrapper

    sse_wrapper.wrapper_server = MagicMock()
    refresh_wrapper_server()
    assert sse_wrapper.wrapper_server is None
    assert sse_wrapper._wrapper_app is None
