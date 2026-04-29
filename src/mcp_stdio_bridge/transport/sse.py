# SPDX-License-Identifier: Unlicense
"""
SSE Transport Router
====================
Branches into either the pure ASGI proxy or the Starlette-based wrapper.
"""

from ..config import settings
from ..logging_utils import logger


async def run_sse_transport() -> None:
    """Dispatches to the correct SSE implementation based on mode."""
    mode = settings.get("mode")
    import uvicorn

    if mode == "proxy":
        logger.debug("Routing to Pure ASGI Proxy Transport.")
        from .sse_proxy import proxy_asgi_app

        app = proxy_asgi_app
    else:
        logger.debug("Routing to Starlette SSE Wrapper Transport.")
        from .sse_wrapper import get_wrapper_app

        app = get_wrapper_app()

    config = uvicorn.Config(
        app,
        host=settings["host"],
        port=settings["port"],
        log_level=settings["logging_level"].lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def refresh_server() -> None:
    """Signal refresh to whichever implementation is loaded."""
    import sys

    if "mcp_stdio_bridge.transport.sse_wrapper" in sys.modules:
        from .sse_wrapper import refresh_wrapper_server

        refresh_wrapper_server()

