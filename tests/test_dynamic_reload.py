# SPDX-License-Identifier: Unlicense
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_reload_settings(tmp_path: Path) -> None:
    """Test that settings are reloaded from disk."""
    import mcp_stdio_bridge.config as config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({"port": 9000}))

    # finalize_settings stores _last_args
    args = MagicMock()
    args.config = str(config_file)
    args.verbose = False
    config.finalize_settings(args)

    with patch("mcp_stdio_bridge.config.get_config_files", return_value=[str(config_file)]):
        config.settings["port"] = 8000
        assert config.reload_settings() is True
        assert config.settings["port"] == 9000


@pytest.mark.anyio
async def test_config_watcher_trigger(tmp_path: Path) -> None:
    """Test that the config watcher detects changes."""
    import mcp_stdio_bridge.main as main

    config_file = tmp_path / "config.yaml"
    config_file.write_text("initial: state")

    with (
        patch("mcp_stdio_bridge.main.get_config_files", return_value=[str(config_file)]),
        patch("mcp_stdio_bridge.main.reload_settings", return_value=True) as mock_reload,
        patch("mcp_stdio_bridge.main.sse_refresh"),
        patch("mcp_stdio_bridge.main.stdio_refresh"),
        patch("anyio.sleep", side_effect=[None, RuntimeError("stop")]),
    ):
        with (
            patch("mcp_stdio_bridge.main.os.path.exists", return_value=True),
            patch("mcp_stdio_bridge.main.os.path.getmtime", side_effect=[100, 200, 200, 200]),
        ):
            try:
                await main.config_watcher()
            except RuntimeError:
                pass
            assert mock_reload.called
