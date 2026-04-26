# SPDX-License-Identifier: Unlicense
"""
Middleware Module
=================

Custom Starlette middleware for enforcing API key authentication,
injecting standard security headers, and global per-IP rate limiting.
"""
import secrets
import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import ASGIApp
from .config import settings
from .logging_utils import logger

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce API key authentication if configured.
    Supports both 'X-API-Key' header and 'api_key' query parameter.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Evaluate the incoming request for a valid API key.

        Args:
            request: The Starlette request object.
            call_next: The next middleware or handler in the chain.

        Returns:
            Response: The HTTP response (401 if unauthorized).
        """
        if settings["api_key"]:
            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            # Use constant-time comparison to mitigate timing attacks.
            if not api_key or not secrets.compare_digest(api_key, settings["api_key"]):
                client_ip = request.client.host if request.client else "unknown"
                logger.warning(f"Unauthorized access attempt from {client_ip}")
                return Response("Unauthorized", status_code=401)
        return await call_next(request)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP sliding-window rate limiter.

    Disabled when rate_limit_requests is 0 (the default). Uses
    X-Forwarded-For when present so proxied clients are bucketed
    by their real IP rather than the proxy's address.
    """
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        # Per-IP state: ip -> (window_start, request_count)
        self._state: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limit = settings.get("rate_limit_requests", 0)
        if not limit:
            return await call_next(request)

        window = settings.get("rate_limit_window", 60)
        client_ip = request.headers.get(
            "X-Forwarded-For",
            request.client.host if request.client else "unknown"
        )
        # Only take the first address from a potentially comma-separated list.
        client_ip = client_ip.split(",")[0].strip()

        now = time.monotonic()
        window_start, count = self._state[client_ip]

        if now - window_start >= window:
            # Window has expired — start a fresh one.
            self._state[client_ip] = (now, 1)
        elif count >= limit:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return Response("Too Many Requests", status_code=429)
        else:
            self._state[client_ip] = (window_start, count + 1)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject standard security headers into all responses
    to protect against common web vulnerabilities.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Inject security headers into the response.

        Args:
            request: The Starlette request object.
            call_next: The next middleware or handler in the chain.

        Returns:
            Response: The modified HTTP response with headers.
        """
        response = await call_next(request)
        if settings["security_headers"]:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Content-Security-Policy"] = "default-src 'none'"

        # Only inject HSTS if the request is over a secure connection.
        if settings["hsts"] and request.scope.get("scheme") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
