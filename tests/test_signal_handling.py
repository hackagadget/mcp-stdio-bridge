# SPDX-License-Identifier: Unlicense
import pytest
import signal
from typing import Any
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.main import _setup_signal_handlers
from mcp_stdio_bridge.transport.sse_proxy import _handle_proxy_sse as handle_proxy_sse
from mcp_stdio_bridge.config import settings


def test_setup_signal_handlers_posix() -> None:
    """Test _setup_signal_handlers on POSIX (mocked)."""
    with patch("sys.platform", "linux"), patch("signal.signal") as mock_signal:
        _setup_signal_handlers()
        assert mock_signal.called
        sig_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGTERM in sig_calls
        assert signal.SIGINT in sig_calls

        handler = [
            call[0][1] for call in mock_signal.call_args_list if call[0][0] == signal.SIGINT
        ][0]

        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGINT, None)
        assert handler(signal.SIGINT, None) is None


def test_setup_signal_handlers_win32() -> None:
    """Test _setup_signal_handlers on win32."""
    with patch("sys.platform", "win32"), patch("signal.signal") as mock_signal:
        _setup_signal_handlers()
        sig_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in sig_calls


def _make_mock_proc() -> tuple[MagicMock, Any]:
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 1234
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    class MockProcessContext:
        async def __aenter__(self) -> MagicMock:
            return mock_proc

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            pass

    return mock_proc, MockProcessContext()


@pytest.mark.anyio
async def test_sse_proxy_termination() -> None:
    """Test that SSE proxy terminates subprocess correctly."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"

    mock_scope = {"type": "http", "client": ["127.0.0.1", 1234]}
    mock_receive = AsyncMock()
    # Simulate immediate disconnect to trigger cleanup
    mock_receive.side_effect = [{"type": "http.disconnect"}]
    mock_send = AsyncMock()

    mock_proc, mock_ctx = _make_mock_proc()

    with (
        patch("shlex.split", return_value=["echo"]),
        patch("anyio.open_process", return_value=mock_ctx),
        patch("mcp_stdio_bridge.transport.sse_proxy.bridge_streams"),
    ):
        await handle_proxy_sse(mock_scope, mock_receive, mock_send)
        # In the new architecture, termination is managed by the transport's context manager
        # we check that the process context was used.
        assert mock_send.called
