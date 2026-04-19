# SPDX-License-Identifier: Unlicense
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
