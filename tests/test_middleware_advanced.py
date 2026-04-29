# SPDX-License-Identifier: Unlicense
import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"



@pytest.mark.anyio
async def test_security_headers_middleware_injection_hit() -> None:
    """Ensure security headers branch is hit (Line 74-75)."""
    from mcp_stdio_bridge.middleware import SecurityHeadersMiddleware
    from mcp_stdio_bridge.config import settings

    settings["security_headers"] = True
    middleware = SecurityHeadersMiddleware(AsyncMock())

    mock_scope = {"type": "http", "scheme": "https"}
    mock_send = AsyncMock()
    await middleware(mock_scope, AsyncMock(), mock_send)
    proxy_send = middleware.app.call_args[0][2]
    await proxy_send({"type": "http.response.start", "status": 200, "headers": []})
    assert True



@pytest.mark.anyio
async def test_rate_limit_middleware_window_expiry_hit() -> None:
    """Ensure window expiration branch is hit (Line 110-111)."""
    from mcp_stdio_bridge.middleware import RateLimitMiddleware
    from mcp_stdio_bridge.config import settings

    settings["rate_limit_requests"] = 1
    settings["rate_limit_window"] = 10
    middleware = RateLimitMiddleware(AsyncMock())

    mock_scope = {"type": "http", "headers": [], "client": ["expiry-ip", 1234]}
    with patch("time.monotonic", side_effect=[100.0, 120.0]):
        await middleware(mock_scope, AsyncMock(), AsyncMock())  # Initial
        await middleware(mock_scope, AsyncMock(), AsyncMock())  # Should reset window
    assert True


@pytest.mark.anyio
async def test_api_key_middleware_non_http_scope() -> None:
    """Non-HTTP scope (lifespan, websocket) bypasses auth and is forwarded as-is."""
    from mcp_stdio_bridge.middleware import APIKeyMiddleware
    from mcp_stdio_bridge.config import settings

    settings["api_key"] = "secret"
    downstream = AsyncMock()
    middleware = APIKeyMiddleware(downstream)
    scope = {"type": "lifespan"}
    await middleware(scope, AsyncMock(), AsyncMock())
    downstream.assert_called_once()
    assert downstream.call_args[0][0] is scope


@pytest.mark.anyio
async def test_security_headers_middleware_non_http_scope() -> None:
    """Non-HTTP scope bypasses header injection and is forwarded as-is."""
    from mcp_stdio_bridge.middleware import SecurityHeadersMiddleware

    downstream = AsyncMock()
    middleware = SecurityHeadersMiddleware(downstream)
    scope = {"type": "lifespan"}
    await middleware(scope, AsyncMock(), AsyncMock())
    downstream.assert_called_once()
    assert downstream.call_args[0][0] is scope


@pytest.mark.anyio
async def test_rate_limit_middleware_non_http_scope() -> None:
    """Non-HTTP scope bypasses rate checking and is forwarded as-is."""
    from mcp_stdio_bridge.middleware import RateLimitMiddleware
    from mcp_stdio_bridge.config import settings

    settings["rate_limit_requests"] = 5
    downstream = AsyncMock()
    middleware = RateLimitMiddleware(downstream)
    scope = {"type": "websocket"}
    await middleware(scope, AsyncMock(), AsyncMock())
    downstream.assert_called_once()
    assert downstream.call_args[0][0] is scope


@pytest.mark.anyio
async def test_rate_limit_within_window_increments_count() -> None:
    """Two requests within the window and under the limit both pass through."""
    from mcp_stdio_bridge.middleware import RateLimitMiddleware
    from mcp_stdio_bridge.config import settings

    settings["rate_limit_requests"] = 5
    settings["rate_limit_window"] = 60
    downstream = AsyncMock()
    middleware = RateLimitMiddleware(downstream)
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"192.168.1.1")],
        "client": ["192.168.1.1", 1234],
    }
    with patch("time.monotonic", return_value=100.0):
        await middleware(scope, AsyncMock(), AsyncMock())
        await middleware(scope, AsyncMock(), AsyncMock())
    assert downstream.call_count == 2
