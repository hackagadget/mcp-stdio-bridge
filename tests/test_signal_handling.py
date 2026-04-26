# SPDX-License-Identifier: Unlicense
import pytest
import signal
import anyio
from unittest.mock import patch, MagicMock, AsyncMock
from mcp_stdio_bridge.main import _setup_signal_handlers
from mcp_stdio_bridge.transport.sse import handle_sse
from mcp_stdio_bridge.transport.stdio import run_stdio_transport
from mcp_stdio_bridge.config import settings

def test_setup_signal_handlers_posix() -> None:
    """Test _setup_signal_handlers on POSIX (mocked)."""
    with patch("sys.platform", "linux"), \
         patch("signal.signal") as mock_signal:
        _setup_signal_handlers()
        assert mock_signal.called
        # Verify it registers SIGTERM
        args, _ = mock_signal.call_args_list[0]
        assert args[0] == signal.SIGTERM
        
        # Test the handler function
        handler = args[1]
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)

def test_setup_signal_handlers_win32() -> None:
    """Test _setup_signal_handlers on win32 (no-op)."""
    with patch("sys.platform", "win32"), \
         patch("signal.signal") as mock_signal:
        _setup_signal_handlers()
        assert not mock_signal.called

def _make_mock_proc():
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 1234
    
    # Mock for 'async with await anyio.open_process(...) as proc'
    class MockProcessContext:
        async def __aenter__(self):
            return mock_proc
        async def __aexit__(self, exc_type, exc, tb):
            pass
    
    return mock_proc, MockProcessContext()

@pytest.mark.anyio
async def test_sse_transport_terminate_error() -> None:
    """Test that SSE transport handles subprocess termination error."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"
    
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"
    
    mock_proc, mock_ctx = _make_mock_proc()
    mock_proc.terminate.side_effect = Exception("Terminate fail")
    
    class MockSSEContext:
        async def __aenter__(self):
            return AsyncMock(), AsyncMock()
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("shlex.split", return_value=["echo"]), \
         patch("anyio.open_process", return_value=mock_ctx), \
         patch("mcp_stdio_bridge.transport.sse.sse.connect_sse", return_value=MockSSEContext()), \
         patch("mcp_stdio_bridge.transport.sse.bridge_streams"):
        
        await handle_sse(mock_request)
        
        assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_stdio_transport_terminate_error() -> None:
    """Test that Stdio transport handles subprocess termination error."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"
    
    mock_proc, mock_ctx = _make_mock_proc()
    mock_proc.terminate.side_effect = Exception("Terminate fail")
    
    # Setup for stdio_server mock
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    
    class MockStdioContext:
        async def __aenter__(self):
            return mock_read, mock_write
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server", return_value=MockStdioContext()), \
         patch("anyio.open_process", return_value=mock_ctx), \
         patch("mcp_stdio_bridge.transport.stdio.bridge_streams"):
        
        await run_stdio_transport()
        
        assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_sse_transport_kill_fallback() -> None:
    """Test that SSE transport falls back to kill() if wait() times out."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"
    
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"
    
    mock_proc, mock_ctx = _make_mock_proc()
    
    async def mock_wait():
        await anyio.sleep(10) # Longer than 2s timeout
    mock_proc.wait.side_effect = mock_wait
    
    class MockSSEContext:
        async def __aenter__(self):
            return AsyncMock(), AsyncMock()
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("shlex.split", return_value=["echo"]), \
         patch("anyio.open_process", return_value=mock_ctx), \
         patch("mcp_stdio_bridge.transport.sse.sse.connect_sse", return_value=MockSSEContext()), \
         patch("mcp_stdio_bridge.transport.sse.bridge_streams"):
        
        await handle_sse(mock_request)
        
        assert mock_proc.terminate.called
        assert mock_proc.kill.called

@pytest.mark.anyio
async def test_stdio_transport_kill_fallback() -> None:
    """Test that Stdio transport falls back to kill() if wait() times out."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"
    
    mock_proc, mock_ctx = _make_mock_proc()
    
    async def mock_wait():
        await anyio.sleep(10)
    mock_proc.wait.side_effect = mock_wait
    
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    
    class MockStdioContext:
        async def __aenter__(self):
            return mock_read, mock_write
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server", return_value=MockStdioContext()), \
         patch("anyio.open_process", return_value=mock_ctx), \
         patch("mcp_stdio_bridge.transport.stdio.bridge_streams"):
        
        await run_stdio_transport()
        
        assert mock_proc.terminate.called
        assert mock_proc.kill.called
