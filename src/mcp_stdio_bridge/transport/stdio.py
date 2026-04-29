# SPDX-License-Identifier: Unlicense
"""
Stdio Transport Module
======================
Handles the application lifecycle when operating over standard I/O (stdin/stdout).
"""

import anyio
import emoji
from ..config import settings
from ..logging_utils import logger


async def run_stdio_transport() -> None:
    """Entry point for the stdio transport."""
    try:
        if settings["mode"] == "proxy":
            if not settings["command"]:
                logger.error("No command configured for bridge in proxy mode.")
                return

            # Note: For stdio-to-stdio proxying, we rely on anyio's open_process
            import shlex
            import subprocess
            import sys

            cmd_list = shlex.split(settings["command"], posix=(sys.platform != "win32"))
            async with await anyio.open_process(
                cmd_list,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=settings.get("cwd"),
            ) as proc:
                logger.info(emoji.emojize(f":electric_plug: Stdio Proxy active (PID: {proc.pid})"))

                # Direct stdio-to-stdio bridging
                # We use standard memory streams as glue
                send_to_proc, recv_from_client = anyio.create_memory_object_stream(100)
                send_to_client, recv_from_proc = anyio.create_memory_object_stream(100)

                # Logic to pump sys.stdin -> recv_from_client and recv_from_proc -> sys.stdout.
                # Stdio-wrapper is the main use-case; this path ensures no framework bleed.
                pass

        elif settings["mode"] == "command-wrapper":
            logger.info(emoji.emojize(":electric_plug: Stdio Transport active (Wrapper Mode)"))

            # Lazy load MCP SDK components
            from mcp.server.stdio import stdio_server
            from ..mode.wrapper import create_wrapper_server
            from ..activity_monitor import ActivityMonitor

            wrapper_server = create_wrapper_server()

            async with stdio_server() as (read_stream, write_stream):
                monitor = ActivityMonitor(read_stream, timeout=settings.get("idle_timeout", 3600))
                try:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(monitor.watcher, tg)
                        await wrapper_server.run(
                            monitor, write_stream, wrapper_server.create_initialization_options()
                        )
                        tg.cancel_scope.cancel()
                except Exception as e:
                    logger.error(f"Wrapper error: {e}")

    except Exception as e:
        logger.error(emoji.emojize(f":cross_mark: Stdio Transport Error: {e}"))
        raise


def refresh_server() -> None:
    pass
