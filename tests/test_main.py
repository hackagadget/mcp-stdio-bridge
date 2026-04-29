# SPDX-License-Identifier: Unlicense
import pytest
import argparse
import yaml
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"



def test_main_arg_error() -> None:
    from mcp_stdio_bridge.main import main as cli_main

    with patch(
        "mcp_stdio_bridge.main.parse_args", side_effect=argparse.ArgumentError(None, "Error")
    ):
        with pytest.raises(SystemExit) as e:
            cli_main()
        assert e.value.code == 1


def test_main_keyboard_interrupt() -> None:
    from mcp_stdio_bridge.main import main as cli_main

    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        with patch("anyio.run", side_effect=KeyboardInterrupt()):
            cli_main()


@pytest.mark.anyio
async def test_start_app_stdio_transport() -> None:
    from mcp_stdio_bridge.main import start_app
    from mcp_stdio_bridge.config import settings

    settings["transport"] = "stdio"
    settings["watch_config"] = False
    with patch(
        "mcp_stdio_bridge.transport.stdio.run_stdio_transport", new_callable=AsyncMock
    ) as mock_run:
        await start_app()
        assert mock_run.called


@pytest.mark.anyio
async def test_start_app_sse_transport() -> None:
    from mcp_stdio_bridge.main import start_app
    from mcp_stdio_bridge.config import settings

    settings["transport"] = "sse"
    settings["mode"] = "proxy"
    settings["watch_config"] = False
    with patch(
        "mcp_stdio_bridge.transport.sse_proxy.run_proxy_transport", new_callable=AsyncMock
    ) as mock_run:
        await start_app()
        assert mock_run.called


@pytest.mark.anyio
async def test_config_watcher_full_reload_cycle() -> None:
    from mcp_stdio_bridge.main import config_watcher

    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise RuntimeError("stop")

    # In the new main.py, we Aliased the refresh functions
    with (
        patch("mcp_stdio_bridge.main.get_config_files", return_value=["dummy.yaml"]),
        patch("mcp_stdio_bridge.main.os.path.exists", return_value=True),
        patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[1, 2, 2, 2]),
        patch("mcp_stdio_bridge.main.reload_settings", return_value=True),
        patch("mcp_stdio_bridge.main.configure_logging"),
        patch("mcp_stdio_bridge.main.logger"),
        patch("mcp_stdio_bridge.main.sse_refresh") as mock_sse_refresh,
        patch("mcp_stdio_bridge.main.stdio_refresh") as mock_stdio_refresh,
        patch("anyio.sleep", mock_sleep),
    ):
        with pytest.raises(RuntimeError, match="stop"):
            await config_watcher()
    assert mock_sse_refresh.called
    assert mock_stdio_refresh.called


@pytest.mark.anyio
async def test_start_app_sse_wrapper_transport() -> None:
    from mcp_stdio_bridge.main import start_app
    from mcp_stdio_bridge.config import settings

    settings["transport"] = "sse"
    settings["mode"] = "command-wrapper"
    settings["watch_config"] = False
    with patch(
        "mcp_stdio_bridge.transport.sse_wrapper.run_wrapper_transport", new_callable=AsyncMock
    ) as mock_run:
        await start_app()
        assert mock_run.called


@pytest.mark.anyio
async def test_start_app_with_watch_config() -> None:
    from mcp_stdio_bridge.main import start_app
    from mcp_stdio_bridge.config import settings

    settings["transport"] = "sse"
    settings["mode"] = "proxy"
    settings["watch_config"] = True
    watcher_started = False

    async def fake_watcher() -> None:
        nonlocal watcher_started
        watcher_started = True

    with (
        patch("mcp_stdio_bridge.main.config_watcher", fake_watcher),
        patch(
            "mcp_stdio_bridge.transport.sse_proxy.run_proxy_transport", new_callable=AsyncMock
        ),
    ):
        await start_app()
    assert watcher_started


@pytest.mark.anyio
async def test_config_watcher_no_files_early_return() -> None:
    from mcp_stdio_bridge.main import config_watcher

    with patch("mcp_stdio_bridge.main.get_config_files", return_value=[]):
        await config_watcher()


def test_main_stdout_reconfigure_exception() -> None:
    from mcp_stdio_bridge.main import main as cli_main

    mock_stdout = MagicMock()
    mock_stdout.reconfigure.side_effect = Exception("Cannot reconfigure")
    with patch("sys.stdout", mock_stdout):
        with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
            with patch("anyio.run"):
                cli_main()


def test_main_custom_logging_load(tmp_path: Path) -> None:
    from mcp_stdio_bridge.main import main as cli_main

    log_config = {"version": 1, "root": {"level": "INFO"}}
    log_file = tmp_path / "custom_log.yaml"
    log_file.write_text(yaml.dump(log_config))
    with patch(
        "sys.argv", ["mcp-stdio-bridge", "--command", "echo", "--logging-config", str(log_file)]
    ):
        with patch("anyio.run"):
            with patch("mcp_stdio_bridge.main.configure_logging", return_value=True) as mock_conf:
                cli_main()
                mock_conf.assert_called_once()
