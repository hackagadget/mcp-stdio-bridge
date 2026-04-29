# SPDX-License-Identifier: Unlicense
import pytest
from unittest.mock import AsyncMock
from mcp_stdio_bridge.middleware import APIKeyMiddleware, RateLimitMiddleware
from mcp_stdio_bridge.config import settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_api_key_middleware_success() -> None:
    """Test API key verification (Success)."""
    settings["api_key"] = "test-key"

    # Mock next app in stack
    next_app = AsyncMock()
    middleware = APIKeyMiddleware(next_app)

    mock_scope = {"type": "http", "headers": [(b"x-api-key", b"test-key")]}

    await middleware(mock_scope, AsyncMock(), AsyncMock())
    assert next_app.called


@pytest.mark.anyio
async def test_api_key_middleware_fail() -> None:
    """Test API key verification (Failure)."""
    settings["api_key"] = "secret"

    next_app = AsyncMock()
    middleware = APIKeyMiddleware(next_app)

    mock_scope = {"type": "http", "headers": [(b"x-api-key", b"wrong")]}

    # We check for the 401 response sent to 'send'
    mock_send = AsyncMock()
    await middleware(mock_scope, AsyncMock(), mock_send)

    assert not next_app.called
    # Check that it sent a 401
    calls = mock_send.call_args_list
    assert any(
        c[0][0].get("status") == 401 for c in calls if c[0][0]["type"] == "http.response.start"
    )


@pytest.mark.anyio
async def test_rate_limit_middleware() -> None:
    """Test rate limiting."""
    settings["rate_limit_requests"] = 1
    settings["rate_limit_window"] = 60

    next_app = AsyncMock()
    middleware = RateLimitMiddleware(next_app)

    mock_scope = {"type": "http", "headers": [], "client": ["1.2.3.4", 1234]}

    # First request: Success
    await middleware(mock_scope, AsyncMock(), AsyncMock())
    assert next_app.call_count == 1

    # Second request: Failure (429)
    mock_send = AsyncMock()
    await middleware(mock_scope, AsyncMock(), mock_send)
    assert next_app.call_count == 1
    assert any(
        c[0][0].get("status") == 429
        for c in mock_send.call_args_list
        if c[0][0]["type"] == "http.response.start"
    )
