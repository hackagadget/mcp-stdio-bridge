# SPDX-License-Identifier: Unlicense
"""
Proxy Logic Module
==================
"""

import anyio
import json
from typing import Any
from anyio.abc import Process
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from ..logging_utils import logger


async def bridge_streams(
    sse_read: MemoryObjectReceiveStream[Any],
    sse_write: MemoryObjectSendStream[Any],
    proc: Process,
) -> None:
    """Orchestrates bidirectional flow between SSE and subprocess. Blocks until complete."""
    logger.info(f"==> [BRIDGE] Started. SSE Read Stream ID: {id(sse_read)}")

    async def sse_to_proc() -> None:
        """SSE -> Subprocess Stdin"""
        logger.info("==> [BRIDGE] 'sse_to_proc' task started.")
        try:
            async with sse_read:
                async for message in sse_read:
                    logger.info(f"==> [BRIDGE] sse_read yielded: {message}")
                    if not message:
                        continue  # pragma: no cover

                    json_text = json.dumps(message) if isinstance(message, dict) else str(message)
                    logger.info(f"==> [BRIDGE] Writing to subprocess stdin: {json_text}")

                    if proc.stdin:
                        await proc.stdin.send(json_text.encode() + b"\n")
                        logger.info("==> [BRIDGE] Subprocess stdin write complete.")
        except Exception as e:
            logger.error(f"==> [BRIDGE] Error in sse_to_proc: {e}")
        finally:
            logger.info("==> [BRIDGE] 'sse_to_proc' finished.")

    async def proc_to_sse() -> None:
        """Subprocess Stdout -> SSE"""
        logger.info("==> [BRIDGE] 'proc_to_sse' task started.")
        try:
            if not proc.stdout:  # pragma: no cover
                logger.error("==> [BRIDGE] Subprocess stdout is missing!")
                return

            async for line in proc.stdout:
                decoded = line.decode().strip()
                logger.info(f"==> [BRIDGE] Subprocess stdout read: {decoded}")
                if decoded:
                    await sse_write.send(decoded)
                    logger.info("==> [BRIDGE] Dispatched stdout line to sse_write.")
        except Exception as e:
            logger.error(f"==> [BRIDGE] Error in proc_to_sse: {e}")
        finally:
            logger.info("==> [BRIDGE] 'proc_to_sse' finished.")

    async def drain_stderr() -> None:
        """Subprocess Stderr -> Logs"""
        logger.info("==> [BRIDGE] 'drain_stderr' task started.")
        if not proc.stderr:
            return  # pragma: no cover
        try:
            async for line in proc.stderr:
                logger.warning(f"==> [SUBPROCESS STDERR] {line.decode().strip()}")
        except Exception:  # noqa: S110  # nosec B110
            pass

    # CRITICAL: We await the TaskGroup to ensure this function blocks
    # as long as the streams or subprocess are active.
    async with anyio.create_task_group() as tg:
        tg.start_soon(sse_to_proc)
        tg.start_soon(proc_to_sse)
        tg.start_soon(drain_stderr)

    logger.info("==> [BRIDGE] All streams finished.")
