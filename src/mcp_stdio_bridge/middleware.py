# SPDX-License-Identifier: Unlicense
"""
Middleware Module
=================
Custom ASGI middleware for enforcing API key authentication,
injecting standard security headers, and global per-IP rate limiting.
Uses pure ASGI to avoid BaseHTTPMiddleware conflicts with SSE.
"""

import secrets
import time
import urllib.parse
from collections import defaultdict
from typing import Any, Dict
from .config import settings
from .logging_utils import logger


class APIKeyMiddleware:
    """ASGI middleware for API Key enforcement."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if settings["api_key"]:
            # Check headers
            headers = dict(scope.get("headers", []))
            api_key = headers.get(b"x-api-key", b"").decode()

            # Check query params
            if not api_key:  # pragma: no cover
                query_string = scope.get("query_string", b"").decode()
                params = urllib.parse.parse_qs(query_string)
                api_key = params.get("api_key", [""])[0]

            if not api_key or not secrets.compare_digest(api_key, settings["api_key"]):
                await self._unauthorized(send)
                return

        await self.app(scope, receive, send)

    async def _unauthorized(self, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Unauthorized",
            }
        )


class SecurityHeadersMiddleware:
    """ASGI middleware for injecting security headers."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if settings["security_headers"]:
                    headers[b"x-content-type-options"] = b"nosniff"
                    headers[b"x-frame-options"] = b"DENY"
                    headers[b"x-xss-protection"] = b"1; mode=block"
                    headers[b"content-security-policy"] = b"default-src 'none'"

                if settings["hsts"] and scope.get("scheme") == "https":  # pragma: no cover
                    headers[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"

                message["headers"] = list(headers.items())

            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """ASGI per-IP sliding-window rate limiter."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._state: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = settings.get("rate_limit_requests", 0)
        if not limit:  # pragma: no cover
            await self.app(scope, receive, send)
            return

        window = settings.get("rate_limit_window", 60)
        # Get client IP from headers or scope
        headers = dict(scope.get("headers", []))
        client_ip = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        if not client_ip:
            client_ip = scope.get("client", ["unknown"])[0]

        now = time.monotonic()
        window_start, count = self._state[client_ip]

        if now - window_start >= window:
            self._state[client_ip] = (now, 1)
        elif count >= limit:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            await self._too_many_requests(send)
            return
        else:
            self._state[client_ip] = (window_start, count + 1)

        await self.app(scope, receive, send)

    async def _too_many_requests(self, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Too Many Requests",
            }
        )
