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

            from ..utils import ExponentialBackoff
            import shlex
            import subprocess
            import sys

            backoff = ExponentialBackoff(settings)

            while True:
                cmd_list = shlex.split(settings["command"], posix=(sys.platform != "win32"))
                logger.info(emoji.emojize(f":electric_plug: Starting Stdio "
                                          f"Proxy: {settings['command']}"))

                try:
                    async with await anyio.open_process(
                        cmd_list,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=settings.get("cwd"),
                    ) as proc:
                        logger.info(
                            emoji.emojize(f":check_mark_button: Stdio Proxy "
                                          f"active (PID: {proc.pid})")
                        )

                        # Logic to pump sys.stdin -> proc.stdin and proc.stdout -> sys.stdout.
                        # (The bridging logic is currently a stub for this transport).
                        await proc.wait()
                        if proc.returncode == 0:
                            logger.info("Subprocess exited cleanly.")
                            break

                        logger.error(f"Subprocess exited with non-zero code: {proc.returncode}")

                except Exception as e:
                    logger.error(f"Failed to start or maintain subprocess: {e}")

                if backoff.can_retry():  # pragma: no cover
                    logger.info(
                        f"Retrying in {backoff.get_delay():.2f}s... "
                        f"({backoff.attempts + 1}/{backoff.max_retries})"
                    )
                    if not await backoff.wait():
                        break
                else:
                    logger.error("Max retries reached or retries disabled. Giving up.")
                    break

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
