# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from unittest.mock import AsyncMock, patch, MagicMock
from mcp_stdio_bridge.config import settings
from mcp_stdio_bridge.transport.stdio import run_stdio_transport

@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'

@pytest.mark.anyio
async def test_stdio_transport_proxy_routing() -> None:
    """Test routing in stdio transport for proxy mode."""
    settings["mode"] = "proxy"
    settings["transport"] = "stdio"
    settings["command"] = "echo hello"

    mock_read = AsyncMock()
    mock_write = AsyncMock()

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value = mock_stdio_ctx

        mock_proc = AsyncMock()
        mock_proc.pid = 1234
        mock_proc.returncode = 0

        with patch("anyio.open_process") as mock_open:
            mock_proc_ctx = AsyncMock()
            mock_proc_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_proc_ctx

            # Use the correct internal path for the patch
            with patch("mcp_stdio_bridge.transport.stdio.bridge_streams",
                       new_callable=AsyncMock) as mock_bridge:
                await run_stdio_transport()
                mock_bridge.assert_called_once()
    await anyio.lowlevel.checkpoint() # type: ignore

@pytest.mark.anyio
async def test_stdio_transport_wrapper_routing() -> None:
    """Test routing in stdio transport for wrapper mode."""
    settings["mode"] = "command-wrapper"
    settings["transport"] = "stdio"

    mock_read = AsyncMock()
    mock_write = AsyncMock()

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value = mock_stdio_ctx

        with patch("mcp_stdio_bridge.transport.stdio.create_wrapper_server") as mock_create:
            mock_server = MagicMock()
            mock_create.return_value = mock_server
            mock_server.run = AsyncMock()

            await run_stdio_transport()
            mock_server.run.assert_called_once()
    await anyio.lowlevel.checkpoint() # type: ignore

@pytest.mark.anyio
async def test_stdio_transport_proxy_no_command() -> None:
    """Test stdio transport handles missing command in proxy mode."""
    settings["mode"] = "proxy"
    settings["command"] = None

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        await run_stdio_transport()
    await anyio.lowlevel.checkpoint() # type: ignore

@pytest.mark.anyio
async def test_stdio_transport_generic_error() -> None:
    """Test stdio transport handles generic exceptions."""
    with patch("mcp_stdio_bridge.transport.stdio.stdio_server",
               side_effect=Exception("Crash")):
        with pytest.raises(Exception, match="Crash"):
            await run_stdio_transport()
    await anyio.lowlevel.checkpoint() # type: ignore

@pytest.mark.anyio
async def test_stdio_transport_proxy_process_fail() -> None:
    """Test stdio transport handles process spawn failure in proxy mode."""
    settings["mode"] = "proxy"
    settings["command"] = "invalid"

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        with patch("anyio.open_process", side_effect=Exception("Spawn fail")):
             with pytest.raises(Exception, match="Spawn fail"):
                 await run_stdio_transport()
    await anyio.lowlevel.checkpoint() # type: ignore

@pytest.mark.anyio
async def test_stdio_transport_proxy_cleanup() -> None:
    """Test stdio transport explicitly terminates proxy process."""
    settings["mode"] = "proxy"
    settings["command"] = "sleep 100"
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_proc = MagicMock()
    mock_proc.returncode = None

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value = mock_stdio_ctx
        with patch("anyio.open_process") as mock_open:
            mock_proc_ctx = AsyncMock()
            mock_proc_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_proc_ctx
            with patch("mcp_stdio_bridge.mode.proxy.bridge_streams",
                       side_effect=Exception("Done")):
                await run_stdio_transport()
                assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_stdio_transport_proc_terminate_branch() -> None:
    """Test stdio transport explicitly terminates proxy process (line 53)."""
    settings["mode"] = "proxy"
    settings["command"] = "sleep 100"
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_proc = MagicMock()
    mock_proc.returncode = None

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value = mock_stdio_ctx
        with patch("anyio.open_process") as mock_open:
            mock_proc_ctx = AsyncMock()
            mock_proc_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_proc_ctx
            # Trigger the finally block by making bridge_streams return
            with patch("mcp_stdio_bridge.mode.proxy.bridge_streams", return_value=None):
                await run_stdio_transport()
                assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_stdio_transport_proc_terminate_fail() -> None:
    """Test stdio transport handles proc.terminate() exception (line 53)."""
    settings["mode"] = "proxy"
    settings["command"] = "sleep 100"
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate.side_effect = RuntimeError("Terminate failed")

    with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value = mock_stdio_ctx
        with patch("anyio.open_process") as mock_open:
            mock_proc_ctx = AsyncMock()
            mock_proc_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_proc_ctx
            with patch("mcp_stdio_bridge.mode.proxy.bridge_streams", return_value=None):
                await run_stdio_transport()
                assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_run_stdio_transport_wrapper_error() -> None:
    """Test that stdio transport handles wrapper server errors."""
    settings["mode"] = "command-wrapper"

    # Mock wrapper server to raise an exception
    mock_server = MagicMock()
    mock_server.run = AsyncMock(side_effect=Exception("Wrapper fail"))

    with patch("mcp_stdio_bridge.transport.stdio.create_wrapper_server",
               return_value=mock_server):
        with patch("mcp_stdio_bridge.transport.stdio.stdio_server") as mock_stdio:
            # Create a mock context manager
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = (AsyncMock(), AsyncMock())
            mock_stdio.return_value = mock_cm

            # This should not raise because it's caught in the mode-specific try/except
            await run_stdio_transport()

    assert mock_server.run.called

def test_refresh_server() -> None:
    """Test that stdio refresh_server executes without error."""
    from mcp_stdio_bridge.transport.stdio import refresh_server
    refresh_server()
