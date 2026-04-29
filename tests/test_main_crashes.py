# SPDX-License-Identifier: Unlicense
import pytest
import sys
from unittest.mock import patch


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_sse_refresh_logic() -> None:
    """Test sse_refresh() function."""
    from mcp_stdio_bridge.main import sse_refresh

    with patch("mcp_stdio_bridge.transport.sse.refresh_server") as mock_refresh:
        sse_refresh()
        assert mock_refresh.called


def test_stdio_refresh_logic() -> None:
    """Test stdio_refresh() function."""
    from mcp_stdio_bridge.main import stdio_refresh

    with patch("mcp_stdio_bridge.transport.stdio.refresh_server") as mock_refresh:
        stdio_refresh()
        assert mock_refresh.called


@pytest.mark.skipif(sys.version_info < (3, 11), reason="BaseExceptionGroup is Python 3.11+")
def test_main_exception_group_handling() -> None:
    """Test that main() handles BaseExceptionGroups containing KeyboardInterrupt."""
    from mcp_stdio_bridge.main import main as cli_main

    try:
        raise BaseExceptionGroup("group", [KeyboardInterrupt()])  # type: ignore[name-defined]  # noqa: F821
    except BaseExceptionGroup as eg:  # type: ignore[name-defined]  # noqa: F821
        mock_eg = eg
    with (
        patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]),
        patch("anyio.run", side_effect=mock_eg),
        patch("mcp_stdio_bridge.main.configure_logging"),
    ):
        cli_main()
        assert True


def test_main_critical_failure_exit() -> None:
    """Test that main() exits 1 on real critical errors (Exception branch)."""
    from mcp_stdio_bridge.main import main as cli_main

    with (
        patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]),
        patch("anyio.run", side_effect=RuntimeError("BOOM")),
        patch("mcp_stdio_bridge.main.configure_logging"),
        patch("mcp_stdio_bridge.main.logger"),
        pytest.raises(SystemExit) as exc,
    ):
        cli_main()
    assert exc.value.code == 1


def test_main_base_exception_exit() -> None:
    """Test that main() exits 1 on BaseException (non-KeyboardInterrupt)."""
    from mcp_stdio_bridge.main import main as cli_main

    # We raise a raw BaseException to hit line 144-147
    with (
        patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]),
        patch("anyio.run", side_effect=BaseException("FATAL")),
        patch("mcp_stdio_bridge.main.configure_logging"),
        patch("mcp_stdio_bridge.main.logger"),
        patch("traceback.print_exc"),
        pytest.raises(SystemExit) as exc,
    ):
        cli_main()
    assert exc.value.code == 1


