# SPDX-License-Identifier: Unlicense
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.config import settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_run_sse_transport_proxy() -> None:
    settings["mode"] = "proxy"

    mock_server = MagicMock()
    mock_server.serve = AsyncMock()

    with patch("uvicorn.Server", return_value=mock_server), patch("uvicorn.Config") as mock_config:
        from mcp_stdio_bridge.transport.sse import run_sse_transport

        await run_sse_transport()

        assert mock_server.serve.called
        # Check that it picked proxy_asgi_app
        from mcp_stdio_bridge.transport.sse_proxy import proxy_asgi_app

        assert mock_config.call_args[0][0] == proxy_asgi_app


@pytest.mark.anyio
async def test_run_sse_transport_wrapper() -> None:
    settings["mode"] = "command-wrapper"

    mock_server = MagicMock()
    mock_server.serve = AsyncMock()
    mock_app = MagicMock()

    with (
        patch("uvicorn.Server", return_value=mock_server),
        patch("uvicorn.Config") as mock_config,
        patch("mcp_stdio_bridge.transport.sse_wrapper.get_wrapper_app", return_value=mock_app),
    ):
        from mcp_stdio_bridge.transport.sse import run_sse_transport

        await run_sse_transport()

        assert mock_server.serve.called
        assert mock_config.call_args[0][0] == mock_app


def test_refresh_server_router() -> None:
    from mcp_stdio_bridge.transport.sse import refresh_server

    mock_wrapper = MagicMock()
    # We need to ensure the mock has the expected function
    mock_wrapper.refresh_wrapper_server = MagicMock()

    with patch.dict("sys.modules", {"mcp_stdio_bridge.transport.sse_wrapper": mock_wrapper}):
        refresh_server()
        assert mock_wrapper.refresh_wrapper_server.called
