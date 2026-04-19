# SPDX-License-Identifier: Unlicense
import sys
import pytest
import argparse
import yaml
from pathlib import Path
from unittest.mock import patch, AsyncMock
from mcp_stdio_bridge.main import main as cli_main, config_watcher
from mcp_stdio_bridge.config import settings

def test_main_config_load_error() -> None:
    """Test that main() handles YAML load errors in config."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--config", "nonexistent.yaml"]):
        # Directly patch load_config to raise an exception when called for the
        # specific file
        with patch("mcp_stdio_bridge.config.load_config",
                   side_effect=Exception("Load fail")):
            with pytest.raises(Exception, match="Load fail"):
                cli_main()

def test_main_arg_error() -> None:
    """Test that main() handles argparse errors."""
    with patch("mcp_stdio_bridge.main.parse_args",
               side_effect=argparse.ArgumentError(None, "Error")):
        with pytest.raises(SystemExit) as e:
            cli_main()
        assert e.value.code == 1

def test_main_keyboard_interrupt() -> None:
    """Test that main() handles KeyboardInterrupt gracefully."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        with patch("anyio.run", side_effect=KeyboardInterrupt()):
            cli_main() # Should not raise

def test_main_startup_fail() -> None:
    """Test that main() exits on startup exception."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        with patch("anyio.run", side_effect=Exception("Failed")):
            with pytest.raises(SystemExit) as e:
                cli_main()
            assert e.value.code == 1

def test_main_startup_generic_fail() -> None:
    """Test that main() handles generic exceptions during startup."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        with patch("anyio.run", side_effect=Exception("Generic startup fail")):
             with pytest.raises(SystemExit) as e:
                 cli_main()
             assert e.value.code == 1

def test_main_custom_logging_load(tmp_path: Path) -> None:
    """Test that main() correctly identifies custom logging."""
    log_config = {"version": 1, "root": {"level": "INFO"}}
    log_file = tmp_path / "custom_log.yaml"
    log_file.write_text(yaml.dump(log_config))

    with patch("sys.argv",
               ["mcp-stdio-bridge", "--command", "echo", "--logging-config", str(log_file)]):
        with patch("anyio.run"):
            with patch("mcp_stdio_bridge.main.configure_logging",
                       return_value=True) as mock_conf:
                cli_main()
                mock_conf.assert_called_once()

def test_main_stdio_custom_logging_warning(tmp_path: Path) -> None:
    """Test that main() warnings about custom logging in stdio mode."""
    log_config = {"version": 1, "root": {"level": "INFO"}}
    log_file = tmp_path / "custom_log.yaml"
    log_file.write_text(yaml.dump(log_config))

    with patch("sys.argv",
               ["mcp-stdio-bridge", "--transport", "stdio", "--command", "echo",
                "--logging-config", str(log_file)]):
        with patch("anyio.run"):
            with patch("mcp_stdio_bridge.main.configure_logging", return_value=True):
                cli_main()

def test_main_stdio_keyboard_interrupt() -> None:
    """Test that main() handles KeyboardInterrupt in stdio mode."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--transport", "stdio", "--command", "echo"]):
        with patch("anyio.run", side_effect=KeyboardInterrupt()):
             cli_main()

def test_main_help() -> None:
    """Test that --help doesn't crash."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--help"]):
        with patch("argparse.ArgumentParser.print_help"):
            with pytest.raises(SystemExit) as e:
                cli_main()
            assert e.value.code == 0

def test_main_loaded_from_log() -> None:
    """Test main() logs the configuration source (line 39)."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        with patch("mcp_stdio_bridge.main.finalize_settings") as mock_finalize:
            # Inject _loaded_from into settings during finalize
            def side_effect(args: argparse.Namespace) -> None:
                settings["_loaded_from"] = "test-path"
            mock_finalize.side_effect = side_effect
            with patch("anyio.run"):
                cli_main()

def test_main_home_config_load_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main() handles errors in home directory config load."""
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("mcp_stdio_bridge.config.load_config",
               side_effect=[{}, Exception("Home load fail")]):
        with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
            with patch("anyio.run"):
                with pytest.raises(Exception, match="Home load fail"):
                    cli_main()

def test_main_cli_execution() -> None:
    """Test that main() works when executed as a module."""
    import subprocess
    # Run the module as a subprocess. This covers the if __name__ == "__main__" block.
    # We pass --help to avoid actually starting the app.
    result = subprocess.run(
        [sys.executable, "-m", "mcp_stdio_bridge.main", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout


@pytest.mark.anyio
async def test_main_config_watcher_enabled() -> None:
    """Test that config_watcher is started when watch_config is enabled."""
    settings["watch_config"] = True
    settings["transport"] = "stdio"
    
    with patch("mcp_stdio_bridge.main.config_watcher",
               new_callable=AsyncMock) as mock_watcher, \
         patch("mcp_stdio_bridge.main.run_stdio_transport",
               new_callable=AsyncMock) as mock_run:
        
        # start_app runs the watcher and the transport in a task group
        from mcp_stdio_bridge.main import start_app
        
        # To test, we need to ensure the task group exits.
        # We can simulate the transport finishing immediately.
        mock_run.return_value = None
        
        # The watcher runs in a loop, so we need to cancel it or make it return
        mock_watcher.side_effect = Exception("Stop")
        
        with pytest.raises(Exception, match="unhandled errors in a TaskGroup"):
             await start_app()
        
        assert mock_watcher.called


@pytest.mark.anyio
async def test_start_app_stdio_transport() -> None:
    """Test start_app with stdio transport."""
    settings["transport"] = "stdio"
    settings["watch_config"] = False
    with patch("mcp_stdio_bridge.main.run_stdio_transport",
               new_callable=AsyncMock) as mock_run:
        from mcp_stdio_bridge.main import start_app
        await start_app()
        assert mock_run.called

@pytest.mark.anyio
async def test_start_app_sse_transport() -> None:
    """Test start_app with sse transport."""
    settings["transport"] = "sse"
    settings["watch_config"] = False
    with patch("mcp_stdio_bridge.main.run_sse_transport",
               new_callable=AsyncMock) as mock_run:
        from mcp_stdio_bridge.main import start_app
        await start_app()
        assert mock_run.called

@pytest.mark.anyio
async def test_config_watcher_reloads_cycle() -> None:
    """Test config_watcher reload cycle with a mock config file."""
    from mcp_stdio_bridge.main import config_watcher
    # We need a temp config file and to patch get_config_files, reload_settings, etc.
    with patch("mcp_stdio_bridge.main.get_config_files", return_value=["dummy.yaml"]), \
         patch("mcp_stdio_bridge.main.os.path.exists", return_value=True), \
         patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[1, 2]), \
         patch("mcp_stdio_bridge.main.reload_settings", return_value=True), \
         patch("mcp_stdio_bridge.main.configure_logging"), \
         patch("mcp_stdio_bridge.main.logger"), \
         patch("anyio.sleep", side_effect=RuntimeError("break")):
        
        with pytest.raises(RuntimeError, match="break"):
            await config_watcher()

@pytest.mark.anyio
async def test_config_watcher_trigger() -> None:
    """Test that config_watcher detects changes and reloads settings."""
    # Setup: a config file exists and we mock reload_settings to return true
    with patch("mcp_stdio_bridge.main.get_config_files", return_value=["test.yaml"]), \
         patch("mcp_stdio_bridge.main.os.path.exists", return_value=True), \
         patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[1, 2]), \
         patch("mcp_stdio_bridge.main.reload_settings", return_value=True), \
         patch("mcp_stdio_bridge.main.configure_logging"), \
         patch("mcp_stdio_bridge.main.logger"), \
         patch("anyio.sleep", side_effect=RuntimeError("break")):
        
        with pytest.raises(RuntimeError, match="break"):
            await config_watcher()

@pytest.mark.anyio
async def test_main_stdio_custom_logging_warning_branch() -> None:
    """Test the 'settings["transport"] == "stdio" and custom_logging' block in main()."""
    settings["transport"] = "stdio"
    with patch("sys.argv", ["mcp-stdio-bridge", "--transport", "stdio"]):
        with patch("mcp_stdio_bridge.main.anyio.run"), \
             patch("mcp_stdio_bridge.main.configure_logging", return_value=True), \
             patch("mcp_stdio_bridge.main.logger.warning") as mock_warn:
            from mcp_stdio_bridge.main import main
            main()
            assert mock_warn.called


@pytest.mark.anyio
async def test_config_watcher_returns_early_with_no_config_files() -> None:
    """config_watcher() returns immediately without looping when get_config_files() is
    empty."""
    with patch("mcp_stdio_bridge.main.get_config_files", return_value=[]), \
         patch("anyio.sleep", side_effect=RuntimeError("should not reach sleep")):
        await config_watcher()  # must return without raising


@pytest.mark.anyio
async def test_config_watcher_full_reload_cycle() -> None:
    """On a detected mtime change, config_watcher() calls reload_settings, reconfigures
    logging, and refreshes both transports."""
    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise RuntimeError("stop")

    with patch("mcp_stdio_bridge.main.get_config_files", return_value=["dummy.yaml"]), \
         patch("mcp_stdio_bridge.main.os.path.exists", return_value=True), \
         patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[1, 2]), \
         patch("mcp_stdio_bridge.main.reload_settings", return_value=True) as mock_reload, \
         patch("mcp_stdio_bridge.main.configure_logging") as mock_cfg_log, \
         patch("mcp_stdio_bridge.main.logger"), \
         patch("mcp_stdio_bridge.transport.sse.refresh_server") as mock_sse_refresh, \
         patch("mcp_stdio_bridge.transport.stdio.refresh_server") as mock_stdio_refresh, \
         patch("anyio.sleep", mock_sleep):
        with pytest.raises(RuntimeError, match="stop"):
            await config_watcher()

    mock_reload.assert_called_once()
    mock_cfg_log.assert_called_once()
    mock_sse_refresh.assert_called_once()
    mock_stdio_refresh.assert_called_once()


@pytest.mark.anyio
async def test_config_watcher_skips_refresh_when_reload_returns_false() -> None:
    """When reload_settings() returns False, configure_logging and transport refresh are
    not called."""
    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise RuntimeError("stop")

    with patch("mcp_stdio_bridge.main.get_config_files", return_value=["dummy.yaml"]), \
         patch("mcp_stdio_bridge.main.os.path.exists", return_value=True), \
         patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[1, 2]), \
         patch("mcp_stdio_bridge.main.reload_settings", return_value=False) as mock_reload, \
         patch("mcp_stdio_bridge.main.configure_logging") as mock_cfg_log, \
         patch("mcp_stdio_bridge.main.logger"), \
         patch("mcp_stdio_bridge.transport.sse.refresh_server") as mock_sse_refresh, \
         patch("mcp_stdio_bridge.transport.stdio.refresh_server") as mock_stdio_refresh, \
         patch("anyio.sleep", mock_sleep):
        with pytest.raises(RuntimeError, match="stop"):
            await config_watcher()

    mock_reload.assert_called_once()
    mock_cfg_log.assert_not_called()
    mock_sse_refresh.assert_not_called()
    mock_stdio_refresh.assert_not_called()


@pytest.mark.anyio
async def test_config_watcher_no_reload_when_file_unchanged() -> None:
    """config_watcher() does not call reload_settings when the config file mtime has not changed."""
    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise RuntimeError("stop")

    with patch("mcp_stdio_bridge.main.get_config_files", return_value=["dummy.yaml"]), \
         patch("mcp_stdio_bridge.main.os.path.exists", return_value=True), \
         patch("mcp_stdio_bridge.main.os.path.getmtime", return_value=1), \
         patch("mcp_stdio_bridge.main.reload_settings") as mock_reload, \
         patch("mcp_stdio_bridge.main.logger"), \
         patch("anyio.sleep", mock_sleep):
        with pytest.raises(RuntimeError, match="stop"):
            await config_watcher()

    mock_reload.assert_not_called()
