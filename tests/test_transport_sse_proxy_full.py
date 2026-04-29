# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.transport.sse_proxy import (
    proxy_asgi_app,
    _handle_proxy_post,
    run_proxy_transport,
    _handle_proxy_sse,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_proxy_asgi_app_unknown_scope() -> None:
    """Test ASGI handler with an unknown scope type (Line 42)."""
    mock_receive = AsyncMock()
    mock_send = AsyncMock()
    # Should just return immediately
    await proxy_asgi_app({"type": "websocket"}, mock_receive, mock_send)
    assert not mock_receive.called
    assert not mock_send.called


@pytest.mark.anyio
async def test_handle_proxy_sse_send_worker() -> None:
    """Test that send_worker correctly forwards messages to the client."""
    from mcp_stdio_bridge.config import settings

    settings["command"] = "echo"

    mock_scope = {"type": "http", "client": ["127.0.0.1", 1234]}
    mock_receive = AsyncMock()

    # Simulate a delay then disconnect to let worker run
    async def disconnect_later() -> dict[str, str]:
        await anyio.sleep(0.1)
        return {"type": "http.disconnect"}

    mock_receive.side_effect = disconnect_later
    mock_send = AsyncMock()

    mock_proc = MagicMock()
    mock_proc.pid = 123
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    class MockCtx:
        async def __aenter__(self) -> Any:
            return mock_proc

        async def __aexit__(self, *args: object) -> None:
            pass

    with (
        patch("anyio.open_process", return_value=MockCtx()),
        patch(
            "mcp_stdio_bridge.transport.sse_proxy.bridge_streams", new_callable=AsyncMock
        ) as mock_bridge,
    ):

        # We manually trigger the send_worker by mocking bridge_streams to send a message
        async def simulate_bridge(r: Any, s: Any, p: Any) -> None:
            await s.send("hello-from-proxy")
            # Wait a bit for send_worker to process
            await anyio.sleep(0.05)

        mock_bridge.side_effect = simulate_bridge

        await _handle_proxy_sse(mock_scope, mock_receive, mock_send)

        # Verify that "hello-from-proxy" was sent as an event: message
        event_sent = any(
            b"hello-from-proxy" in c[0][0].get("body", b"")
            for c in mock_send.call_args_list
            if c[0][0]["type"] == "http.response.body"
        )
        assert event_sent


@pytest.mark.anyio
async def test_proxy_asgi_app_auth_missing() -> None:
    from mcp_stdio_bridge.config import settings

    settings["api_key"] = "valid-key"
    mock_scope = {
        "type": "http",
        "headers": [],
        "query_string": b"",
        "path": "/sse",
        "method": "GET",
    }
    mock_send = AsyncMock()
    await proxy_asgi_app(mock_scope, AsyncMock(), mock_send)
    assert any(
        c[0][0].get("status") == 401
        for c in mock_send.call_args_list
        if c[0][0]["type"] == "http.response.start"
    )


@pytest.mark.anyio
async def test_handle_proxy_post_exception() -> None:
    from mcp_stdio_bridge.transport import sse_proxy

    session_id = "test-session"
    mock_stream = AsyncMock()
    mock_stream.send.side_effect = Exception("Stream Error")
    sse_proxy.sessions[session_id] = mock_stream
    mock_scope = {"type": "http", "query_string": b"session_id=test-session"}
    mock_receive = AsyncMock()
    mock_receive.side_effect = [{"type": "http.request", "body": b"{}", "more_body": False}]
    mock_send = AsyncMock()
    try:
        await _handle_proxy_post(mock_scope, mock_receive, mock_send)
        assert any(
            c[0][0].get("status") == 500
            for c in mock_send.call_args_list
            if c[0][0]["type"] == "http.response.start"
        )
    finally:
        if session_id in sse_proxy.sessions:
            del sse_proxy.sessions[session_id]


@pytest.mark.anyio
async def test_handle_proxy_sse_exception() -> None:
    mock_scope = {"type": "http", "client": ["127.0.0.1", 1234]}
    mock_send = AsyncMock()
    mock_send.side_effect = Exception("Unexpected Crash")
    await _handle_proxy_sse(mock_scope, AsyncMock(), mock_send)
    assert True


@pytest.mark.anyio
async def test_proxy_asgi_app_routing_post() -> None:
    from mcp_stdio_bridge.config import settings

    settings["api_key"] = None
    mock_scope = {
        "type": "http",
        "path": "/messages",
        "method": "POST",
        "query_string": b"session_id=none",
    }
    mock_send = AsyncMock()
    await proxy_asgi_app(mock_scope, AsyncMock(), mock_send)
    assert any(
        c[0][0].get("status") == 400
        for c in mock_send.call_args_list
        if c[0][0]["type"] == "http.response.start"
    )


@pytest.mark.anyio
async def test_proxy_asgi_app_lifespan() -> None:
    mock_receive = AsyncMock()
    mock_receive.side_effect = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    mock_send = AsyncMock()
    async with anyio.create_task_group() as tg:
        tg.start_soon(proxy_asgi_app, {"type": "lifespan"}, mock_receive, mock_send)
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()
    assert any(
        c[0][0]["type"] == "lifespan.startup.complete" for c in mock_send.call_args_list
    )


@pytest.mark.anyio
async def test_proxy_asgi_app_auth_query_string() -> None:
    from mcp_stdio_bridge.config import settings

    settings["api_key"] = "valid-key"
    mock_scope = {
        "type": "http",
        "headers": [],
        "query_string": b"api_key=valid-key",
        "path": "/sse",
        "method": "GET",
    }
    mock_send = AsyncMock()
    with patch(
        "mcp_stdio_bridge.transport.sse_proxy._handle_proxy_sse", new_callable=AsyncMock
    ) as mock_sse:
        await proxy_asgi_app(mock_scope, AsyncMock(), mock_send)
        assert mock_sse.called


@pytest.mark.anyio
async def test_proxy_asgi_app_404() -> None:
    from mcp_stdio_bridge.config import settings

    settings["api_key"] = None
    mock_scope = {
        "type": "http",
        "path": "/unknown",
        "method": "GET",
        "headers": [],
        "query_string": b"",
    }
    mock_send = AsyncMock()
    await proxy_asgi_app(mock_scope, AsyncMock(), mock_send)
    assert any(
        c[0][0].get("status") == 404
        for c in mock_send.call_args_list
        if c[0][0]["type"] == "http.response.start"
    )


@pytest.mark.anyio
async def test_handle_proxy_post_success() -> None:
    from mcp_stdio_bridge.transport import sse_proxy

    session_id = "test-session"
    mock_stream = AsyncMock()
    sse_proxy.sessions[session_id] = mock_stream
    mock_scope = {"type": "http", "query_string": b"session_id=test-session"}
    mock_receive = AsyncMock()
    mock_receive.side_effect = [
        {"type": "http.request", "body": b'{"jsonrpc": "2.0",', "more_body": True},
        {"type": "http.request", "body": b'"method": "test"}', "more_body": False},
    ]
    mock_send = AsyncMock()
    try:
        await _handle_proxy_post(mock_scope, mock_receive, mock_send)
        assert mock_stream.send.called
    finally:
        if session_id in sse_proxy.sessions:
            del sse_proxy.sessions[session_id]


@pytest.mark.anyio
async def test_handle_proxy_post_disconnect() -> None:
    from mcp_stdio_bridge.transport import sse_proxy

    session_id = "test-session"
    sse_proxy.sessions[session_id] = AsyncMock()
    mock_scope = {"type": "http", "query_string": b"session_id=test-session"}
    mock_receive = AsyncMock()
    mock_receive.side_effect = [{"type": "http.disconnect"}]
    await _handle_proxy_post(mock_scope, mock_receive, AsyncMock())
    if session_id in sse_proxy.sessions:
        del sse_proxy.sessions[session_id]
    assert True


@pytest.mark.anyio
async def test_run_proxy_transport_init() -> None:
    mock_server = MagicMock()
    mock_server.serve = AsyncMock()
    with patch("uvicorn.Server", return_value=mock_server):
        await run_proxy_transport()
        assert mock_server.serve.called
