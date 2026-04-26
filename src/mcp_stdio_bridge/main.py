# SPDX-License-Identifier: Unlicense
"""
Main Entry Point
================

Coordinates the initialization of configuration, logging, and starting
the appropriate transport (SSE or Stdio). Manages high-level lifecycle
events and exception handling for the application start-up.
"""
import anyio
import sys
import argparse
import emoji
import os
import signal
from typing import Any
from .config import parse_args, finalize_settings, settings, reload_settings, get_config_files
from .logging_utils import configure_logging, logger
from .transport import run_stdio_transport, run_sse_transport

def _setup_signal_handlers() -> None:
    """Register signal handlers for graceful shutdown on POSIX."""
    if sys.platform != "win32":
        def handle_sigterm(signum: int, frame: Any) -> None:
            logger.info(emoji.emojize(f":door: Received signal {signum}. Shutting down..."))
            # Raising KeyboardInterrupt allows anyio.run to catch it and 
            # trigger graceful cleanup of task groups and context managers.
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, handle_sigterm)

async def config_watcher() -> None:
    """
    Background task that monitors configuration files for changes.
    Triggers a reload when any file is modified.
    """
    config_files = get_config_files()
    if not config_files:
        return

    # Track last modified times
    last_mtimes = {}
    for f in config_files:
        if os.path.exists(f):
            last_mtimes[f] = os.path.getmtime(f)

    logger.debug(f"Config watcher started for files: {config_files}")

    while True:
        await anyio.sleep(5) # Poll every 5 seconds
        changed = False
        for f in config_files:
            if os.path.exists(f):
                mtime = os.path.getmtime(f)
                if mtime > last_mtimes.get(f, 0):
                    last_mtimes[f] = mtime
                    changed = True

        if changed:
            logger.info(emoji.emojize(":arrows_counterclockwise: Configuration change "
                                      "detected. Reloading..."))
            if reload_settings():
                # Re-apply logging level if changed
                configure_logging(settings["logging_level"], settings["logging_config"])
                # Signal other components to refresh
                from .transport.sse import refresh_server as sse_refresh
                from .transport.stdio import refresh_server as stdio_refresh
                sse_refresh()
                stdio_refresh()
                logger.info(emoji.emojize(":check_mark_button: Configuration reloaded "
                                          "successfully."))

async def start_app() -> None:
    """
    Orchestrates the concurrent execution of the transport and the config watcher.
    """
    async with anyio.create_task_group() as tg:
        if settings.get("watch_config"):
            tg.start_soon(config_watcher)

        if settings["transport"] == "stdio":
            await run_stdio_transport()
        else:
            await run_sse_transport()

def main() -> None:
    """
    Primary CLI Entry point.
    Parses arguments, loads configuration files, initializes the logging
    subsystem, and branches into either SSE (web server) or Stdio transport.
    """
    try:
        args = parse_args()
    except argparse.ArgumentError as e:
        print(f"CLI Error: {e}", file=sys.stderr)
        sys.exit(1)

    finalize_settings(args)
    _setup_signal_handlers()

    # Setup Logging subsystem
    custom_logging = configure_logging(settings["logging_level"], settings["logging_config"])
    if custom_logging:
        logger.info(f"Using custom logging configuration from: {settings['logging_config']}")

    # Branch into the requested transport
    try:
        if settings["transport"] == "stdio" and custom_logging:
            logger.warning(emoji.emojize(":warning: Custom logging active in Stdio mode. "
                                         "Ensure no handlers use sys.stdout!"))

        anyio.run(start_app)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Application failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
