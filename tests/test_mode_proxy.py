# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch, MagicMock
from mcp_stdio_bridge.mode.proxy import bridge_streams


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _make_mock_proc() -> AsyncMock:
    proc = AsyncMock()
    proc.terminate = MagicMock()
    proc.stdout = AsyncMock()
    proc.stdin = AsyncMock()
    proc.stderr = AsyncMock()
    return proc


@pytest.mark.anyio
async def test_bridge_streams_basic() -> None:
    """Test successful bidirectional flow."""
    mock_sse_read, mock_sse_write = anyio.create_memory_object_stream(10)
    mock_send_to_sse, mock_recv_from_proc = anyio.create_memory_object_stream(10)
    mock_proc = _make_mock_proc()

    async def mock_stdout() -> AsyncIterator[bytes]:
        yield b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'

    mock_proc.stdout.__aiter__.side_effect = mock_stdout

    async with anyio.create_task_group() as tg:
        tg.start_soon(bridge_streams, mock_sse_write, mock_send_to_sse, mock_proc)
        await anyio.sleep(0.1)  # Let tasks start
        await mock_sse_read.send({"jsonrpc": "2.0", "method": "test"})
        await anyio.sleep(0.1)
        assert mock_proc.stdin.send.called
        msg = await mock_recv_from_proc.receive()
        assert "jsonrpc" in msg
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_bridge_streams_error_handling() -> None:
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_sse_read.__aiter__.side_effect = Exception("SSE Failure")
    await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)


@pytest.mark.anyio
async def test_bridge_streams_stdout_missing() -> None:
    """Test error when stdout is missing."""
    send_to_sse, mock_sse_read = anyio.create_memory_object_stream(1)
    mock_sse_write, _ = anyio.create_memory_object_stream(1)

    mock_proc = _make_mock_proc()
    mock_proc.stdout = None

    with patch("mcp_stdio_bridge.mode.proxy.logger") as mock_logger:
        async with anyio.create_task_group() as tg:
            tg.start_soon(bridge_streams, mock_sse_read, mock_sse_write, mock_proc)
            await anyio.sleep(0.1)  # Ensure tasks start
            await send_to_sse.aclose()  # Finish the loop

        assert any(
            "Subprocess stdout is missing" in call[0][0]
            for call in mock_logger.error.call_args_list
        )


@pytest.mark.anyio
async def test_bridge_streams_proc_to_sse_exception() -> None:
    """Exception while iterating proc.stdout is caught and logged (lines 58-59)."""
    mock_sse_read, mock_sse_write = anyio.create_memory_object_stream(10)
    mock_send_to_sse, _ = anyio.create_memory_object_stream(10)
    mock_proc = _make_mock_proc()

    mock_proc.stdout.__aiter__.side_effect = RuntimeError("read pipe broken")

    with patch("mcp_stdio_bridge.mode.proxy.logger") as mock_logger:
        async with anyio.create_task_group() as tg:
            tg.start_soon(bridge_streams, mock_sse_write, mock_send_to_sse, mock_proc)
            await anyio.sleep(0.1)
            tg.cancel_scope.cancel()

    error_msgs = [str(call) for call in mock_logger.error.call_args_list]
    assert any("Error in proc_to_sse" in m for m in error_msgs)


@pytest.mark.anyio
async def test_bridge_streams_stderr_content_and_exception() -> None:
    """drain_stderr logs content lines (line 70) and handles iteration exception (line 71)."""
    mock_sse_read, _ = anyio.create_memory_object_stream(10)
    mock_send_to_sse, _ = anyio.create_memory_object_stream(10)
    mock_proc = _make_mock_proc()
    mock_proc.stdout = None  # make proc_to_sse return early

    async def stderr_then_fail() -> AsyncIterator[bytes]:  # type: ignore[return]
        yield b"stderr: something happened\n"
        raise RuntimeError("stderr pipe broken")

    mock_proc.stderr.__aiter__.side_effect = stderr_then_fail

    with patch("mcp_stdio_bridge.mode.proxy.logger") as mock_logger:
        async with anyio.create_task_group() as tg:
            tg.start_soon(bridge_streams, mock_sse_read, mock_send_to_sse, mock_proc)
            await anyio.sleep(0.2)
            tg.cancel_scope.cancel()

    warn_msgs = [str(call) for call in mock_logger.warning.call_args_list]
    assert any("something happened" in m for m in warn_msgs)


@pytest.mark.anyio
async def test_bridge_streams_stderr_missing() -> None:
    """Test early return when stderr is missing."""
    send_to_sse, mock_sse_read = anyio.create_memory_object_stream(1)
    mock_sse_write, _ = anyio.create_memory_object_stream(1)

    mock_proc = _make_mock_proc()
    mock_proc.stderr = None

    with patch("mcp_stdio_bridge.mode.proxy.logger") as mock_logger:
        async with anyio.create_task_group() as tg:
            tg.start_soon(bridge_streams, mock_sse_read, mock_sse_write, mock_proc)
            await anyio.sleep(0.1)  # Ensure tasks start
            await send_to_sse.aclose()

        # Verify that 'drain_stderr' task started (Line 63)
        assert any(
            "'drain_stderr' task started" in call[0][0] for call in mock_logger.info.call_args_list
        )
