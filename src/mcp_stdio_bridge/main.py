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


def _write_pid_file(path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        logger.debug(f"PID file written: {path}")
    except OSError as e:
        logger.warning(f"Could not write PID file {path!r}: {e}")


def _remove_pid_file(path: str) -> None:
    try:
        os.unlink(path)
        logger.debug(f"PID file removed: {path}")
    except OSError:
        pass


def _daemonize() -> None:
    """Detach from the controlling terminal and run as a background daemon (POSIX only)."""
    if sys.platform == "win32":  # pragma: no cover
        logger.warning("--daemonize is not supported on Windows; running in foreground")
        return

    # First fork: let the shell think the command has finished.
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Become the session leader of a new session with no controlling terminal.
    os.setsid()

    # Second fork: ensure the daemon can never re-acquire a controlling terminal.
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Redirect the three standard file descriptors to /dev/null.
    devnull_fd = os.open(os.devnull, os.O_RDWR)
    try:
        for fd in (0, 1, 2):
            os.dup2(devnull_fd, fd)
    finally:
        os.close(devnull_fd)


def _reload_process(pid_file: str | None) -> None:
    """Send SIGHUP to a running bridge process identified by pid_file."""
    if sys.platform == "win32":
        print("--reload is not supported on Windows (no SIGHUP)", file=sys.stderr)
        sys.exit(1)

    if not pid_file:
        print(
            "--reload requires a PID file; set --pid-file or pid_file in config",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(pid_file, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except FileNotFoundError:
        print(f"PID file not found: {pid_file}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError) as e:
        print(f"Could not read PID file {pid_file!r}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        print(f"No process with PID {pid} — stale PID file?", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        pass  # process exists but we lack permission for the probe; try the signal anyway

    sighup = getattr(signal, "SIGHUP", None)
    try:
        os.kill(pid, sighup)  # type: ignore[arg-type]
        print(f"Sent SIGHUP to process {pid}", file=sys.stderr)
    except (ProcessLookupError, PermissionError) as e:
        print(f"Could not signal process {pid}: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


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

        _sighup = getattr(signal, "SIGHUP", None)
        if _sighup is not None:

            def handle_sighup(signum: int, frame: Any) -> None:
                logger.info("Received SIGHUP — reloading configuration")
                if reload_settings():
                    configure_logging(settings["logging_level"], settings["logging_config"])
                    sse_refresh()
                    stdio_refresh()
                    logger.info("Configuration reloaded")

            signal.signal(_sighup, handle_sighup)

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

    if getattr(args, "reload", False):
        _reload_process(settings.get("pid_file"))

    _setup_signal_handlers()
    configure_logging(settings["logging_level"], settings["logging_config"])

    if settings.get("daemonize"):
        _daemonize()

    pid_file = settings.get("pid_file")
    if pid_file:
        _write_pid_file(pid_file)
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
    finally:
        if pid_file:
            _remove_pid_file(pid_file)


if __name__ == "__main__":
    main()
