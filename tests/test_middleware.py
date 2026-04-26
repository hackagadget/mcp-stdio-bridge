# SPDX-License-Identifier: Unlicense
import time
from unittest.mock import patch
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from mcp_stdio_bridge.config import settings
from mcp_stdio_bridge.transport.sse import create_app

async def _noop_handler(request: Request) -> Response:
    return Response("OK", status_code=200)

def test_api_key_middleware_unauthorized() -> None:
    """Test API key middleware blocks requests with wrong key."""
    settings["api_key"] = "secret-key"
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/sse", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401

def test_api_key_query_param() -> None:
    """Test API key middleware accepts key in query parameters."""
    settings["api_key"] = "query-key"
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/sse?api_key=query-key")
            assert response.status_code != 401

def test_security_headers() -> None:
    """Test that security headers middleware adds expected headers."""
    settings["security_headers"] = True
    settings["api_key"] = None
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/sse")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "Content-Security-Policy" in response.headers

def test_hsts_header() -> None:
    """Test that HSTS header is added when configured."""
    settings["hsts"] = True
    settings["api_key"] = None
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app, base_url="https://testserver") as client:
            response = client.get("/sse")
            assert "Strict-Transport-Security" in response.headers

# ---------------------------------------------------------------------------
# RateLimitMiddleware tests
# ---------------------------------------------------------------------------

def test_rate_limit_disabled_allows_all_requests() -> None:
    """With rate_limit_requests=0 (disabled) every request passes through."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 0
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            for _ in range(20):
                response = client.get("/sse")
                assert response.status_code == 200

def test_rate_limit_allows_requests_within_limit() -> None:
    """Requests within the limit in a single window are allowed."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 5
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            for _ in range(5):
                response = client.get("/sse")
                assert response.status_code == 200

def test_rate_limit_blocks_excess_requests() -> None:
    """The (limit+1)th request in a window receives 429; prior requests are allowed."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 3
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            for _ in range(3):
                assert client.get("/sse").status_code == 200
            assert client.get("/sse").status_code == 429

def test_rate_limit_resets_after_window() -> None:
    """After the window expires the counter resets and requests are allowed again."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 2
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            client.get("/sse")
            client.get("/sse")
            assert client.get("/sse").status_code == 429
            # Advance time past the window so the next request gets a fresh bucket.
            future = time.monotonic() + 61
            with patch("mcp_stdio_bridge.middleware.time.monotonic", return_value=future):
                assert client.get("/sse").status_code == 200

def test_rate_limit_separate_buckets_per_ip() -> None:
    """Two different client IPs each get their own independent counter."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 2
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            # Exhaust limit for 127.0.0.1
            client.get("/sse")
            client.get("/sse")
            assert client.get("/sse").status_code == 429
            # A different IP via X-Forwarded-For should still be allowed
            response = client.get("/sse", headers={"X-Forwarded-For": "10.0.0.1"})
            assert response.status_code == 200

def test_rate_limit_uses_x_forwarded_for() -> None:
    """X-Forwarded-For header is preferred over connection IP for bucketing."""
    settings["api_key"] = None
    settings["rate_limit_requests"] = 1
    settings["rate_limit_window"] = 60
    with patch("mcp_stdio_bridge.transport.sse.handle_sse", new=_noop_handler):
        app = create_app()
        with TestClient(app) as client:
            client.get("/sse", headers={"X-Forwarded-For": "192.168.1.1"})
            # Second request from same forwarded IP should be rate-limited
            response = client.get("/sse", headers={"X-Forwarded-For": "192.168.1.1"})
            assert response.status_code == 429
            # But a different forwarded IP is still fine
            response = client.get("/sse", headers={"X-Forwarded-For": "192.168.1.2"})
            assert response.status_code == 200
