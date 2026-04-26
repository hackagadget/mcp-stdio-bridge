# SPDX-License-Identifier: Unlicense
"""
Stdio Transport Module
======================

Handles the application lifecycle when operating over standard I/O (stdin/stdout).
Connects either the proxy bridging logic or the internal wrapper server
directly to the process's standard streams.
"""
import anyio
import sys
import subprocess
import emoji
from mcp.server.stdio import stdio_server

from ..config import settings
from ..logging_utils import logger
from ..mode import bridge_streams, create_wrapper_server
from ..activity_monitor import ActivityMonitor

def refresh_server() -> None:
    """
    Signal dynamic reload. For stdio, this is informational as the
    loop is usually short-lived or direct.
    """
    logger.debug("Stdio transport notified of dynamic reload.")

async def run_stdio_transport() -> None:
    """
    Main loop for the Stdio transport.
    Sets up the standard I/O streams and dispatches to the appropriate mode.
    """
    try:
        async with stdio_server() as (read_stream, write_stream):
            if settings["mode"] == "proxy":
                if not settings["command"]:
                    logger.error("No command configured for bridge in proxy mode.")
                    return

                logger.info(emoji.emojize(":electric_plug: Stdio Transport active (Proxy Mode)"))
                # Windows-aware command splitting
                import shlex
                cmd_list = shlex.split(settings["command"], posix=(sys.platform != "win32"))

                # Spawn the external subprocess with piped I/O.
                async with await anyio.open_process(
                    cmd_list,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                ) as proc:
                    logger.info(emoji.emojize(f":gear: Subprocess started (PID: {proc.pid})"))
                    try:
                        # Start bidirectional bridging.
                        await bridge_streams(read_stream, write_stream, proc)
                    finally:
                        if proc.returncode is None:
                            try:
                                logger.info(f"Terminating subprocess (PID: {proc.pid})...")
                                proc.terminate()
                                # Give it a short window to exit gracefully
                                with anyio.move_on_after(2):
                                    await proc.wait()
                                
                                if proc.returncode is None:
                                    logger.warning(f"Subprocess (PID: {proc.pid}) did not exit. "
                                                   "Killing...")
                                    proc.kill()
                            except Exception as e:
                                logger.error(emoji.emojize(f":cross_mark: subprocess terminate "
                                                           f"error: {e}"))
                            logger.info(emoji.emojize(":minus: Subprocess terminated"))

            elif settings["mode"] == "command-wrapper":
                logger.info(emoji.emojize(":electric_plug: Stdio Transport active (Wrapper Mode)"))

                # Connect the internal wrapper server directly to the stdio streams.
                wrapper_server = create_wrapper_server()

                monitor = ActivityMonitor(read_stream, timeout=settings.get("idle_timeout", 3600))

                try:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(monitor.watcher, tg)

                        try:
                            await wrapper_server.run(
                                monitor,
                                write_stream,
                                wrapper_server.create_initialization_options()
                            )
                        finally:
                            tg.cancel_scope.cancel()
                except Exception as e:
                    logger.error(f"Wrapper error: {e}")

    except Exception as e:
        logger.error(emoji.emojize(f":cross_mark: Stdio Transport Error: {e}"))
        raise
