# SPDX-License-Identifier: Unlicense
"""
Proxy Logic Module
==================

Implements the low-level bidirectional bridging between SSE streams
and an external subprocess's standard I/O streams. Orchestrates the
concurrent forwarding of JSON-RPC messages.
"""
import anyio
import anyio.abc
import json
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from typing import Any, AsyncIterable
from ..config import settings
from ..logging_utils import logger

async def read_lines(stream: AsyncIterable[bytes]) -> AsyncIterable[bytes]:
    """
    Asynchronous generator that yields full lines from a byte stream.
    Implements message size enforcement.
    """
    buffer = b""
    max_size = settings.get("max_message_size", 1024 * 1024)

    try:
        async for chunk in stream:
            buffer += chunk

            # Incremental safety check: prevent buffer from growing indefinitely without newlines.
            if len(buffer) > max_size * 2:
                 raise ValueError(f"Message stream buffer exceeded safety limits "
                                  f"({len(buffer)} bytes).")

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if len(line) > max_size:
                    raise ValueError(f"Message too large: {len(line)} bytes (Max: {max_size})")
                yield line
    except anyio.ClosedResourceError:
        if buffer:
            yield buffer
    except Exception as e:
        if isinstance(e, ValueError):
             raise
        logger.debug(f"Stream read terminated: {e}")
        if buffer and b"\n" not in buffer:
             yield buffer

async def bridge_streams(sse_read: MemoryObjectReceiveStream[Any],
                         sse_write: MemoryObjectSendStream[Any],
                         proc: anyio.abc.Process) -> None:
    """
    Orchestrates the bidirectional flow of JSON-RPC messages between
    the SSE client and the bridged subprocess.
    """
    last_activity = anyio.current_time()
    idle_timeout = settings.get("idle_timeout", 3600)

    async def update_activity() -> None:
        nonlocal last_activity
        last_activity = anyio.current_time()

    async with anyio.create_task_group() as tg:
        async def sse_to_proc() -> None:
            """Forwards messages from the SSE client to the subprocess's stdin."""
            try:
                async for message in sse_read:
                    await update_activity()
                    if isinstance(message, Exception):
                        logger.error(f"SSE Read Error: {message}")
                        break

                    # Extract the JSON payload and enforce size limits.
                    json_text = message.model_dump_json()
                    if len(json_text) > settings.get("max_message_size", 1024 * 1024):
                        logger.warning("Dropped oversized message from SSE client.")
                        continue

                    if settings.get("verbose"):
                        logger.debug(f"SSE -> PROC: {json_text}")

                    if proc.stdin is not None:
                        await proc.stdin.send(json_text.encode() + b"\n")
                    else:
                        logger.error("Subprocess stdin is not available")
                        break
            except Exception as e:
                logger.debug(f"sse_to_proc terminated: {e}")
            finally:
                tg.cancel_scope.cancel()

        async def proc_to_sse() -> None:
            """Forwards lines from the subprocess's stdout to the SSE client."""

            if proc.stdout is None:
                logger.error("Subprocess stdout is not available.")
                tg.cancel_scope.cancel()
                return

            try:
                async for line in read_lines(proc.stdout):
                    await update_activity()
                    if not line.strip():
                        continue

                    if settings.get("verbose"):
                        logger.debug(f"PROC -> SSE: {line.decode().strip()}")

                    try:
                        # Validate that the line is a proper JSON-RPC message.
                        msg_dict = json.loads(line)
                        await sse_write.send(msg_dict)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON from subprocess: {line.decode()[:100]}...")
                        pass
            except Exception as e:
                logger.error(f"proc_to_sse error: {e}")
            finally:
                # Ensure the entire task group (and session) is canceled if this direction dies.
                tg.cancel_scope.cancel()

        async def drain_stderr() -> None:
            """Drains and logs stderr from the subprocess to prevent pipe blocking."""
            if proc.stderr is None:
                logger.error("Subprocess stderr is not available.")
                return

            try:
                async for line in read_lines(proc.stderr):
                    await update_activity()
                    if line.strip():
                        logger.error(f"Subprocess Stderr: {line.decode().strip()}")
            except Exception as e:
                logger.error(f"Error draining stderr from subprocess: {e}")

        async def idle_watcher() -> None:
            """Monitor for session inactivity and terminate if timeout reached."""
            if idle_timeout <= 0:
                return

            # Dynamic check interval: at most 10 seconds, but shorter if idle_timeout is very small.
            check_interval = max(0.1, min(10.0, idle_timeout / 5.0))

            while True:
                await anyio.sleep(check_interval)
                if anyio.current_time() - last_activity > idle_timeout:
                    logger.warning(f"Session idle for > {idle_timeout}s. Terminating.")
                    tg.cancel_scope.cancel()
                    break

        # Execute all directions concurrently.
        tg.start_soon(sse_to_proc)
        tg.start_soon(proc_to_sse)
        tg.start_soon(drain_stderr)
        tg.start_soon(idle_watcher)

