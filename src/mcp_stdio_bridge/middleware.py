# SPDX-License-Identifier: Unlicense
"""
Middleware Module
=================

Custom Starlette middleware for enforcing API key authentication
and injecting standard security headers into HTTP responses.
"""
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware.base import RequestResponseEndpoint
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
