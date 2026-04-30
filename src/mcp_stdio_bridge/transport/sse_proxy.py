# SPDX-License-Identifier: Unlicense
"""
Zero-Dependency SSE Proxy Implementation
========================================
This module implements the MCP SSE transport using raw ASGI.
It is completely isolated from Starlette and the MCP SDK.
"""

import anyio
import uvicorn
import shlex
import sys
import subprocess
import emoji
import json
import uuid
import secrets
import urllib.parse
from typing import Dict, Any

from ..config import settings
from ..logging_utils import logger
from ..mode.proxy import bridge_streams

# Global state for active sessions
sessions: Dict[str, Any] = {}
connection_semaphore = None
retry_manager = None


async def proxy_asgi_app(scope: Any, receive: Any, send: Any) -> None:
    """Pure ASGI Entry point for Proxy Mode."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] != "http":
        return

    # 1. AUTHENTICATION
    if settings["api_key"]:
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode()
        if not api_key:
            query = urllib.parse.parse_qs(scope.get("query_string", b"").decode())
            api_key = query.get("api_key", [""])[0]

        if not api_key or not secrets.compare_digest(api_key, settings["api_key"]):
            await _send_plain_response(send, 401, b"Unauthorized")
            return

    path = scope["path"]
    method = scope["method"]

    # 2. ROUTING
    if path == "/sse" and method == "GET":
        await _handle_proxy_sse(scope, receive, send)
    elif path.startswith("/messages") and method == "POST":
        await _handle_proxy_post(scope, receive, send)
    else:
        await _send_plain_response(send, 404, b"Not Found")


async def _send_plain_response(send: Any, status: int, body: bytes) -> None:
    """Helper to send a non-streaming response."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _handle_proxy_post(scope: Any, receive: Any, send: Any) -> None:
    """Handles POST /messages/ without high-level framework overhead."""
    query = urllib.parse.parse_qs(scope["query_string"].decode())
    session_id = query.get("session_id", [None])[0]

    if not session_id or session_id not in sessions:
        await _send_plain_response(send, 400, b"Invalid Session")
        return

    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        elif message["type"] == "http.disconnect":
            return

    try:
        data = json.loads(body)
        logger.info(f"==> [PROXY-POST] Received for {session_id}")
        await sessions[session_id].send(data)
        await send(
            {
                "type": "http.response.start",
                "status": 202,
                "headers": [(b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})
    except Exception as e:
        logger.error(f" [PROXY-POST] Error: {e}")
        await _send_plain_response(send, 500, b"Internal Error")


async def _handle_proxy_sse(scope: Any, receive: Any, send: Any) -> None:
    """Handles GET /sse: Orchestrates the subprocess and event stream."""
    global connection_semaphore, retry_manager
    client_ip = scope.get("client", ["unknown"])[0]

    try:
        if connection_semaphore is None:
            connection_semaphore = anyio.CapacityLimiter(settings["max_connections"])

        if retry_manager is None:
            from ..utils import ExponentialBackoff

            retry_manager = ExponentialBackoff(settings)

        async with connection_semaphore:
            # Enforce backoff if there were previous crashes
            if retry_manager.attempts > 0:
                delay = retry_manager.get_delay()
                logger.warning(
                    f"Throttling connection from {client_ip} "
                    f"due to previous crash ({delay:.2f}s delay)"
                )
                await anyio.sleep(delay)

            session_id = str(uuid.uuid4())
            logger.info(f"==> [PROXY-SSE] Session {session_id} starting for {client_ip}")

            send_to_proxy, recv_from_sse = anyio.create_memory_object_stream(100)
            send_to_client, recv_from_proxy = anyio.create_memory_object_stream(100)
            sessions[session_id] = send_to_proxy

            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/event-stream"),
                        (b"cache-control", b"no-cache"),
                        (b"connection", b"keep-alive"),
                    ],
                }
            )

            endpoint_msg = f"event: endpoint\ndata: /messages/?session_id={session_id}\n\n"
            await send(
                {"type": "http.response.body", "body": endpoint_msg.encode(), "more_body": True}
            )

            async def send_worker() -> None:
                try:
                    async with recv_from_proxy:
                        async for message in recv_from_proxy:
                            data = json.dumps(message) if not isinstance(message, str) else message
                            payload = f"event: message\ndata: {data}\n\n"
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": payload.encode(),
                                    "more_body": True,
                                }
                            )
                except Exception:  # noqa: S110  # nosec B110
                    pass

            try:
                cmd_list = shlex.split(settings["command"], posix=(sys.platform != "win32"))
                async with anyio.create_task_group() as tg:
                    tg.start_soon(send_worker)
                    async with await anyio.open_process(
                        cmd_list,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=settings.get("cwd"),
                    ) as proc:
                        logger.info(f"==> [PROXY-SSH] Subprocess PID: {proc.pid}")
                        try:
                            await bridge_streams(recv_from_sse, send_to_client, proc)
                        finally:
                            await send_to_client.aclose()
                        tg.cancel_scope.cancel()

                        if proc.returncode != 0:
                            retry_manager.attempts += 1
                            logger.error(
                                f"Subprocess crashed with code {proc.returncode}. "
                                "Next connection will be delayed."
                            )
                        else:
                            retry_manager.reset()
            except Exception as e:
                retry_manager.attempts += 1
                logger.error(f"Bridge error or subprocess failure: {e}")
            finally:
                if session_id in sessions:
                    del sessions[session_id]
                logger.info(f"==> [PROXY-SSE] Session {session_id} cleanup complete.")

    except Exception as e:
        logger.error(f" [PROXY-SSE] Crash: {e}")


async def run_proxy_transport() -> None:
    """Launches Uvicorn for Proxy Mode with ZERO framework wrappers."""
    logger.info(
        emoji.emojize(
            f":rocket: [PURE-PROXY] Running on http://{settings['host']}:{settings['port']}/sse"
        )
    )
    config = uvicorn.Config(
        proxy_asgi_app,
        host=settings["host"],
        port=settings["port"],
        log_level=settings["logging_level"].lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()
