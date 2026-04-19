# SPDX-License-Identifier: Unlicense
"""
SSE Transport Module
====================

Implements the HTTP/SSE transport layer using Starlette and Uvicorn.
Handles the web application lifecycle, route dispatching, and secure
server execution.
"""
import anyio
import uvicorn
import ssl
import shlex
import sys
import subprocess
import emoji
import time
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import Response
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport

from ..config import settings
from ..logging_utils import logger
from ..middleware import APIKeyMiddleware, SecurityHeadersMiddleware
from ..mode import bridge_streams, create_wrapper_server
from ..activity_monitor import ActivityMonitor

# Global transport and limit objects
sse = SseServerTransport("/messages/")
connection_semaphore = None
wrapper_server = None

def refresh_server() -> None:
    """
    Called when configuration changes. Reset cached server components.
    """
    global wrapper_server, connection_semaphore
    wrapper_server = None
    # Semaphore is updated on next connection if settings changed connections count
    connection_semaphore = None
    logger.debug("SSE server components refreshed for dynamic reload.")

async def handle_sse(request: Request) -> Response:
    """
    HTTP endpoint handler for the MCP SSE connection.
    Spawns a new subprocess (proxy mode) or runs an internal server (wrapper mode)
    for every established SSE session.

    Args:
        request: The Starlette request object.

    Returns:
        Response: The HTTP response starting the SSE event stream.
    """
    global connection_semaphore, wrapper_server
    start_time = time.time()
    client_ip = request.headers.get("X-Forwarded-For",
                                    request.client.host if request.client else "unknown")

    # Lazy-initialize the semaphore to enforce global connection limits.
    if connection_semaphore is None:
        connection_semaphore = anyio.CapacityLimiter(settings["max_connections"])

    # Attempt to acquire a connection slot without blocking.
    try:
        connection_semaphore.acquire_nowait()
    except anyio.WouldBlock:
        logger.warning(emoji.emojize(f":warning: Connection limit reached for {client_ip}. "
                                     f"Returning 503."))
        return Response("Connection limit reached", status_code=503)

    try:
        if settings["mode"] == "proxy":
            if not settings["command"]:
                logger.error("No command configured for bridge in proxy mode.")
                return Response("Server Configuration Error", status_code=500)

            logger.info(emoji.emojize(f":electric_plug: Connection established from {client_ip} "
                                      f"(Proxy Mode)"))
            cmd_list = shlex.split(settings["command"], posix=(sys.platform != "win32"))

            # Spawn the external subprocess with piped I/O.
            async with await anyio.open_process(
                cmd_list,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            ) as proc:
                logger.info(emoji.emojize(f":gear: Subprocess started (PID: {proc.pid}) for "
                                          f"{client_ip}"))

                try:
                    # Establish the SSE session context.
                    async with sse.connect_sse(request.scope, request.receive,
                                               request._send) as (sse_read, sse_write):
                        logger.info(emoji.emojize(f":check_mark_button: SSE session active for "
                                                  f"{client_ip}"))
                        try:
                            # Start bidirectional bridging.
                            await bridge_streams(sse_read, sse_write, proc)
                        except Exception as e:
                            logger.error(emoji.emojize(f":cross_mark: Bridge Error for "
                                                       f"{client_ip}: {e}"))
                finally:
                    # Explicit cleanup ensuring the subprocess is terminated.
                    if proc.returncode is None:
                        try:
                            proc.terminate()
                        except Exception as e:
                            logger.error(emoji.emojize(f":cross_mark: subprocess terminate "
                                                       f"error: {e}"))
                        logger.info(emoji.emojize(":minus: Subprocess terminated for {client_ip}"))

        elif settings["mode"] == "command-wrapper":
            logger.info(emoji.emojize(f":electric_plug: Connection established from "
                                      f"{client_ip} (Wrapper Mode)"))

            # Lazy-initialize the internal wrapper server.
            if wrapper_server is None:
                wrapper_server = create_wrapper_server()

            async with sse.connect_sse(request.scope, request.receive,
                                       request._send) as (sse_read, sse_write):
                logger.info(emoji.emojize(f":check_mark_button: SSE session active for "
                                          f"{client_ip}"))

                monitor = ActivityMonitor(sse_read, timeout=settings.get("idle_timeout", 3600))

                try:
                    async with anyio.create_task_group() as tg:
                        # Start the activity watcher
                        tg.start_soon(monitor.watcher, tg)

                        # In wrapper mode, bind the internal MCP server directly to the
                        # monitored SSE client.
                        try:
                            await wrapper_server.run(
                                monitor,
                                sse_write,
                                wrapper_server.create_initialization_options()
                            )
                        finally:
                            tg.cancel_scope.cancel()
                except Exception as e:
                    logger.error(emoji.emojize(f":cross_mark: Wrapper Error for {client_ip}: {e}"))

    except Exception as e:
        logger.error(emoji.emojize(f":cross_mark: Server Error for {client_ip}: {e}"))
        return Response("Internal Server Error", status_code=500)
    finally:
        # slot release and detailed disconnect logging.
        if connection_semaphore:
            connection_semaphore.release()
        duration = time.time() - start_time
        logger.info(emoji.emojize(f":door: Client {client_ip} disconnected (Duration: "
                                  f"{duration:.2f}s)"))

    return Response()

def create_app() -> Starlette:
    """
    Application Factory: Initializes Starlette with routes and security middleware.

    Returns:
        Starlette: The configured application instance.
    """
    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]
    return Starlette(
        debug=False,
        routes=routes,
        middleware=[
            Middleware(CORSMiddleware, allow_origins=settings["cors_origins"],
                       allow_methods=["*"], allow_headers=["*"]),
            Middleware(APIKeyMiddleware),
            Middleware(SecurityHeadersMiddleware)
        ]
    )

async def run_sse_transport() -> None:
    """
    Starts the Uvicorn server to host the SSE transport.
    """
    # Configure SSL context if certificate files are provided
    ssl_context = None
    if settings["ssl_certfile"] and settings["ssl_keyfile"]:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if settings["ssl_protocol"] == "TLSv1_3":
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3
        else:
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        ssl_context.load_cert_chain(
            settings["ssl_certfile"],
            settings["ssl_keyfile"],
            password=settings["ssl_keyfile_password"]
        )

        if settings["ssl_ca_certs"]:
            ssl_context.load_verify_locations(settings["ssl_ca_certs"])
            if settings["ssl_crlfile"]:
                ssl_context.load_verify_locations(settings["ssl_crlfile"])
                ssl_context.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF

            if settings["ssl_client_cert_required"]:
                ssl_context.verify_mode = ssl.CERT_REQUIRED
            else:
                ssl_context.verify_mode = ssl.CERT_OPTIONAL

        if settings["ssl_ciphers"]:
            ssl_context.set_ciphers(settings["ssl_ciphers"])

    logger.info(emoji.emojize(f":rocket: MCP Bridge running on http{'s' if ssl_context else ''}://{settings['host']}:{settings['port']}/sse"))

    app = create_app()
    uvicorn_config = uvicorn.Config(
        app,
        host=settings["host"],
        port=settings["port"],
        log_level=settings["logging_level"].lower()
    )
    if ssl_context:
        uvicorn_config.ssl = ssl_context

    server = uvicorn.Server(uvicorn_config)
    await server.serve()
