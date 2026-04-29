# SPDX-License-Identifier: Unlicense
"""
Starlette-based SSE Wrapper Implementation
==========================================
"""

import anyio
import emoji
import uvicorn
from typing import Any, Optional
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport

from ..config import settings
from ..logging_utils import logger
from ..middleware import APIKeyMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from ..mode import create_wrapper_server
from ..activity_monitor import ActivityMonitor

# Global state
_wrapper_app: Optional[Starlette] = None
_sse_transport: Optional[SseServerTransport] = None
connection_semaphore: Optional[anyio.CapacityLimiter] = None
wrapper_server: Optional[Any] = None


async def handle_sse(request: Request) -> Response:
    global connection_semaphore, wrapper_server, _sse_transport

    try:
        client_ip = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        )

        if connection_semaphore is None:
            connection_semaphore = anyio.CapacityLimiter(settings["max_connections"])

        async with connection_semaphore:
            if wrapper_server is None:
                wrapper_server = create_wrapper_server()

            if _sse_transport is None:  # pragma: no cover
                return Response()
            async with _sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as (sse_read, sse_write):
                logger.info(
                    emoji.emojize(f":check_mark_button: SSE session active for {client_ip}")
                )
                monitor = ActivityMonitor(sse_read, timeout=settings.get("idle_timeout", 3600))
                try:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(monitor.watcher, tg)
                        await wrapper_server.run(
                            monitor, sse_write, wrapper_server.create_initialization_options()
                        )
                        tg.cancel_scope.cancel()
                except Exception as e:
                    logger.error(f"Wrapper error for {client_ip}: {e}")
    except Exception as e:
        logger.error(f"SSE Handler crash: {e}")
    return Response()


def get_wrapper_app() -> Starlette:
    global _wrapper_app, _sse_transport
    if _wrapper_app is not None:
        return _wrapper_app

    _sse_transport = SseServerTransport("/messages/")
    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=_sse_transport.handle_post_message),
    ]
    _wrapper_app = Starlette(
        debug=False,
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings["cors_origins"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
            Middleware(APIKeyMiddleware),
            Middleware(RateLimitMiddleware),
            Middleware(SecurityHeadersMiddleware),
        ],
    )
    return _wrapper_app


def refresh_wrapper_server() -> None:
    global wrapper_server, connection_semaphore, _wrapper_app
    wrapper_server = None
    connection_semaphore = None
    _wrapper_app = None


async def run_wrapper_transport() -> None:
    """Launches Uvicorn for Wrapper Mode."""
    logger.info(
        emoji.emojize(
            f":rocket: [WRAPPER] Running on"
            f" http://{settings['host']}:{settings['port']}/sse"
        )
    )
    config = uvicorn.Config(
        get_wrapper_app(),
        host=settings["host"],
        port=settings["port"],
        log_level=settings["logging_level"].lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()
