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
import secrets
import signal
from typing import Any
from .config import parse_args, finalize_settings, settings, reload_settings, get_config_files
from .logging_utils import configure_logging, logger


# Module-level references for tests to patch easily
def sse_refresh() -> None:
    """Signal refresh to SSE transport."""
    try:
        from .transport.sse import refresh_server

        refresh_server()
    except ImportError:  # pragma: no cover
        pass


def stdio_refresh() -> None:
    """Signal refresh to Stdio transport."""
    try:
        from .transport.stdio import refresh_server

        refresh_server()
    except ImportError:  # pragma: no cover
        pass


def _setup_signal_handlers() -> None:
    """Register signal handlers for graceful shutdown."""
    shutdown_in_progress = False

    def handle_shutdown(signum: int, frame: Any) -> None:
        nonlocal shutdown_in_progress
        if shutdown_in_progress:
            return
        shutdown_in_progress = True
        logger.info(emoji.emojize(f":door: Received signal {signum}. Shutting down..."))
        raise KeyboardInterrupt

    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)


async def config_watcher() -> None:
    """Background task to watch for config changes."""
    config_files = get_config_files()
    if not config_files:
        return
    last_mtimes = {f: os.path.getmtime(f) for f in config_files if os.path.exists(f)}

    while True:
        await anyio.sleep(5)
        changed = False
        for f in config_files:
            if os.path.exists(f):
                mtime = os.path.getmtime(f)
                if mtime > last_mtimes.get(f, 0):
                    last_mtimes[f] = mtime
                    changed = True
        if changed:
            logger.info(
                emoji.emojize(
                    ":arrows_counterclockwise: Configuration change detected. Reloading..."
                )
            )
            if reload_settings():
                configure_logging(settings["logging_level"], settings["logging_config"])
                # Signal other components to refresh
                sse_refresh()
                stdio_refresh()
                logger.info(
                    emoji.emojize(":check_mark_button: Configuration reloaded successfully.")
                )


async def start_app() -> None:
    """Orchestrates transport and config watcher."""
    async with anyio.create_task_group() as tg:
        if settings.get("watch_config"):
            tg.start_soon(config_watcher)

        if settings["transport"] == "stdio":
            from .transport.stdio import run_stdio_transport

            await run_stdio_transport()
        else:
            # SSE TRANSPORT: Dispatch based on mode
            if settings.get("mode") == "proxy":
                from .transport.sse_proxy import run_proxy_transport

                await run_proxy_transport()
            else:
                from .transport.sse_wrapper import run_wrapper_transport

                await run_wrapper_transport()


def main() -> None:
    """Primary CLI Entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:  # noqa: S110  # nosec B110
            pass

    try:
        args = parse_args()
    except argparse.ArgumentError as e:
        print(f"CLI Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.generate_api_key and not args.generate_config:
        print(secrets.token_urlsafe(32))
        sys.exit(0)

    if args.generate_config:
        from .config import generate_config

        print(generate_config(args), end="")
        sys.exit(0)

    if args.generate_client_config:
        from .config import generate_client_config, client_config_info

        info = client_config_info(args.generate_client_config)
        print(f"Client:      {args.generate_client_config}", file=sys.stderr)
        print(f"Destination: {info['path']}", file=sys.stderr)
        print(f"Note:        {info['note']}", file=sys.stderr)
        print(
            "Warning:     Config formats are subject to change without notice."
            " Verify against your client's current documentation.",
            file=sys.stderr,
        )
        content = generate_client_config(args, args.generate_client_config)
        output_path = getattr(args, "output", None)
        if output_path:
            import pathlib

            resolved = pathlib.Path(output_path).resolve()
            with open(resolved, "w", encoding="utf-8") as fh:
                fh.write(content)
            print(f"Written to:  {resolved}", file=sys.stderr)
        else:
            print(content, end="")
        sys.exit(0)

    if args.check_config:
        from .config import check_config

        sys.exit(check_config(args, args.warnings_as_errors))

    finalize_settings(args)
    _setup_signal_handlers()
    configure_logging(settings["logging_level"], settings["logging_config"])

    try:
        anyio.run(start_app)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # On Python â‰¤3.10 the exceptiongroup backport makes BaseExceptionGroup a
        # subclass of Exception; check via duck-typing so both versions are handled.
        exceptions = getattr(e, "exceptions", None)
        if exceptions is not None and all(isinstance(s, KeyboardInterrupt) for s in exceptions):
            pass  # anyio-wrapped clean shutdown
        else:
            import traceback

            logger.critical(f"Application failed to start: {e}")
            traceback.print_exc()
            sys.exit(1)
    except BaseException as e:
        # On Python â‰¥3.11 BaseExceptionGroup subclasses BaseException directly.
        exceptions = getattr(e, "exceptions", None)
        if exceptions is not None and all(isinstance(s, KeyboardInterrupt) for s in exceptions):
            pass  # anyio-wrapped clean shutdown
        else:
            import traceback

            logger.critical(f"Application failed to start: {e}")
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
