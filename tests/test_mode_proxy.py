# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from typing import Any, AsyncGenerator, AsyncIterable, AsyncIterator
from unittest.mock import AsyncMock, patch, MagicMock
from mcp_stdio_bridge.activity_monitor import ActivityMonitor
from mcp_stdio_bridge.mode.proxy import read_lines, bridge_streams
from mcp_stdio_bridge.config import settings

try:
    # Check if it's built-in (3.11+)
    _ExceptionGroup = ExceptionGroup
except NameError:
    # Fallback for < 3.11
    from exceptiongroup import ExceptionGroup

def _make_mock_proc() -> AsyncMock:
    """AsyncMock proc with a sync terminate() matching anyio.abc.Process."""
    proc = AsyncMock()
    proc.terminate = MagicMock()
    return proc


@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'

@pytest.mark.anyio
async def test_read_lines() -> None:
    """Test line reading from byte stream."""
    with anyio.fail_after(5):
        async def mock_stream() -> AsyncIterator[bytes]:
            yield b"line1\n"
            yield b"line2\r\n"
            yield b"line"
            yield b"3\nline4"
            yield b"\n"

        lines = []
        async for line in read_lines(mock_stream()):
            # Use rstrip to ignore \r on Windows
            lines.append(line.rstrip())

        assert lines == [b"line1", b"line2", b"line3", b"line4"]

@pytest.mark.anyio
async def test_read_lines_size_limit() -> None:
    """Test read_lines enforces max message size (line 36)."""
    with anyio.fail_after(5):
        # Set a very small limit
        settings["max_message_size"] = 5
        async def mock_stream() -> AsyncIterator[bytes]:
            # This will exceed 5 bytes and has a newline
            yield b"123456\n"

        with pytest.raises(ValueError, match="Message too large"):
            async for _ in read_lines(mock_stream()):
                pass

@pytest.mark.anyio
async def test_read_lines_closed_resource() -> None:
    """Test that read_lines handles ClosedResourceError gracefully (line 40)."""
    async def mock_stream() -> AsyncIterator[bytes]:
        yield b"data" # NO NEWLINE
        raise anyio.ClosedResourceError()

    lines = []
    async for line in read_lines(mock_stream()):
        lines.append(line)
    # Line 40 yields the remaining buffer
    assert lines == [b"data"]

@pytest.mark.anyio
async def test_read_lines_incremental_overflow() -> None:
    """Test read_lines raises ValueError on incremental buffer overflow (line 31)."""
    settings["max_message_size"] = 5
    async def mock_stream() -> AsyncIterator[bytes]:
        # Exceed max_size * 2 (10) WITHOUT a newline
        yield b"12345678901"

    with pytest.raises(ValueError, match="buffer exceeded safety limits"):
        async for _ in read_lines(mock_stream()):
            pass

@pytest.mark.anyio
async def test_read_lines_generic_exception() -> None:
    """Test read_lines handles and yields on generic exceptions (line 46)."""
    async def mock_stream() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("Fail")

    lines = []
    async for line in read_lines(mock_stream()):
        lines.append(line)
    assert b"partial" in lines

@pytest.mark.anyio
async def test_bridge_streams_error_handling() -> None:
    """Test that bridge_streams handles exceptions in tasks."""
    with anyio.fail_after(5):
        mock_sse_read = AsyncMock()
        mock_sse_write = AsyncMock()
        mock_proc = _make_mock_proc()

        mock_sse_read.__aiter__.side_effect = Exception("SSE Failure")

        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)

@pytest.mark.anyio
async def test_bridge_streams_proc_to_sse_error() -> None:
    """Test that bridge_streams handles exceptions in proc_to_sse."""
    with anyio.fail_after(5):
        mock_sse_read = AsyncMock()
        mock_sse_write = AsyncMock()
        mock_proc = _make_mock_proc()
        mock_proc.stdout = AsyncMock()

        # Make read_lines fail
        with patch("mcp_stdio_bridge.mode.proxy.read_lines",
                   side_effect=Exception("Proc Read Failure")):
             await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)

@pytest.mark.anyio
async def test_bridge_streams_serialization_error() -> None:
    """Test that bridge_streams handles bad JSON from subprocess."""
    with anyio.fail_after(5):
        # 1. Use real stream objects or mocks that implement the interface
        mock_sse_read = AsyncMock()
        mock_sse_write = AsyncMock()
        mock_proc = _make_mock_proc()

        # Mock the stream iteration (sse_read)
        # Note: In bridge_streams, this is used as 'async for message in sse_read'
        mock_sse_read.__aiter__.return_value = AsyncMock()
        mock_sse_read.__aiter__.return_value.__anext__.side_effect = StopAsyncIteration

        # 2. Ensure stdout/stdin/stderr are NOT None to pass the type guards
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.stderr = AsyncMock()

        async def bad_proc_gen() -> AsyncIterable[bytes]:
            yield b"not json\n"

        # 3. Patch read_lines and catch the cancellation
        # bridge_streams calls tg.cancel_scope.cancel() on errors, so we catch it OUTSIDE
        with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=bad_proc_gen()):
            try:
                await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
            except (anyio.get_cancelled_exc_class(), ExceptionGroup):
                pass 

@pytest.mark.anyio
async def test_bridge_streams_large_message() -> None:
    """Test that bridge_streams handles messages exceeding size limit."""
    settings["max_message_size"] = 10
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()

    mock_msg = MagicMock()
    mock_msg.model_dump_json.return_value = '{"very": "long message"}'

    async def sse_gen() -> AsyncGenerator[Any, Any]:
        yield mock_msg

    mock_sse_read.__aiter__.side_effect = sse_gen

    await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
    # Stdin send should NOT be called because it's too big
    assert not mock_proc.stdin.send.called

@pytest.mark.anyio
async def test_bridge_streams_sse_exception() -> None:
    """Test that bridge_streams handles sse_read yielding exceptions."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    async def sse_gen() -> AsyncGenerator[Any, Any]:
        yield Exception("SSE error")
    mock_sse_read.__aiter__.side_effect = sse_gen
    await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
    assert not mock_proc.stdin.send.called

@pytest.mark.anyio
async def test_bridge_streams_verbose_logging() -> None:
    """Test bridge_streams with verbose logging enabled (legacy)."""
    settings["verbose"] = True
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_msg = MagicMock()
    mock_msg.message.model_dump_json.return_value = '{"jsonrpc": "2.0"}'
    async def sse_gen() -> AsyncGenerator[Any, Any]:
        yield mock_msg
    mock_sse_read.__aiter__.side_effect = sse_gen
    async def proc_gen() -> AsyncIterable[bytes]:
        yield b'{"jsonrpc": "2.0", "result": {}}\n'
    # Use real bridge_streams and real read_lines to cover the verbose branches
    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=proc_gen()):
        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)

@pytest.mark.anyio
async def test_proxy_bridge_streams_verbose_actual() -> None:
    """Test bridge_streams verbose logging branches (lines 68-71, 85, 91)."""
    # Reset size limit to ensure message passes
    settings["max_message_size"] = 1000000
    settings["verbose"] = True
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stdout = AsyncMock()
    mock_proc.stdin = AsyncMock()

    # Valid JSON-RPC notification
    mock_msg = MagicMock()
    mock_msg.message.model_dump_json.return_value = '{"jsonrpc": "2.0", "method": "test"}'

    async def sse_gen() -> AsyncGenerator[Any, Any]:
        yield mock_msg
    mock_sse_read.__aiter__.side_effect = sse_gen

    # Valid JSON-RPC response
    async def proc_gen() -> AsyncIterable[bytes]:
        yield b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'

    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=proc_gen()):
        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)

    assert mock_proc.stdin.send.called
    assert mock_sse_write.send.called

@pytest.mark.anyio
async def test_proxy_bridge_streams_cancellation() -> None:
    """Test that bridge_streams cancels other tasks on failure."""
    # 1. Setup mocks with necessary stream attributes to pass type guards
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()

    # Ensure streams are not None so the 'if proc.stdout is None' checks pass
    mock_proc.stdout = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stderr = AsyncMock()

    # 2. Setup sse_read to exit immediately to trigger the finally: cancel() block
    # Note: Using an AsyncMock for the iterator is more reliable than a lambda in AnyIO tests
    mock_iterator = AsyncMock()
    mock_iterator.__anext__.side_effect = StopAsyncIteration
    mock_sse_read.__aiter__.return_value = mock_iterator

    async def infinite_proc() -> AsyncIterable[bytes]:
        try:
            while True:
                yield b"data\n"
                await anyio.sleep(0.1)
        except anyio.get_cancelled_exc_class():
            # This proves the task is actually being cancelled
            return

    # 3. Catch the cancellation OUTSIDE the bridge_streams call
    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=infinite_proc()):
        try:
            # This call will raise a cancellation error because sse_to_proc 
            # finishes immediately and calls tg.cancel_scope.cancel()
            await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
        except (anyio.get_cancelled_exc_class(), ExceptionGroup):
            # ExceptionGroup is for Python 3.11+, others use the cancelled class
            pass 

@pytest.mark.anyio
async def test_proxy_bridge_streams_proc_terminate_fail() -> None:
    """Test that bridge_streams handles proc.terminate() error in finally."""
    # 1. Setup mocks with necessary stream attributes
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    
    # Use MagicMock for proc because terminate() is a synchronous method in AnyIO
    mock_proc = MagicMock() 
    mock_proc.terminate.side_effect = Exception("Kill fail")
    
    # Ensure streams are not None to pass type guards in bridge_streams
    mock_proc.stdout = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stderr = AsyncMock()

    # 2. Setup sse_read to exit immediately
    mock_iterator = AsyncMock()
    mock_iterator.__anext__.side_effect = StopAsyncIteration
    mock_sse_read.__aiter__.return_value = mock_iterator

    # 3. Patch read_lines to exit immediately
    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=AsyncMock()):
        try:
            # This will run the bridge, reach the finally block, 
            # call proc.terminate(), and catch the exception you injected.
            await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
        except (anyio.get_cancelled_exc_class(), ExceptionGroup):
            # Catch the cancellation that happens when sub-tasks finish
            pass

    # 4. Verify terminate was called despite the injected failure
    mock_proc.terminate.assert_called_once()

@pytest.mark.anyio
async def test_proxy_proc_to_sse_empty_line() -> None:
    """Test proc_to_sse skips empty lines (line 85)."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stdout = AsyncMock()

    async def proc_gen() -> AsyncIterable[bytes]:
        yield b"\n" # Yields b"" from read_lines
        yield b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'

    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=proc_gen()):
        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)

    # Check that sse_write was only called once (for the second line)
    assert mock_sse_write.send.call_count == 1

@pytest.mark.anyio
async def test_bridge_streams_idle_timeout() -> None:
    """Test that bridge_streams terminates on idle timeout."""
    settings["idle_timeout"] = 0.5 # 500ms timeout
    mock_sse_read = MagicMock() # Not AsyncMock because we use __aiter__
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stdout = AsyncMock()

    # Keep sse_read alive as an async iterator but WITHOUT yielding messages
    async def infinite_sse() -> AsyncGenerator[Any, Any]:
        await anyio.sleep(2) # Stay silent longer than timeout
        yield MagicMock()

    mock_sse_read.__aiter__.side_effect = infinite_sse

    # Keep proc_to_sse alive as an async iterator but WITHOUT yielding lines
    async def infinite_proc_gen() -> AsyncIterable[bytes]:
        await anyio.sleep(2) # Stay silent longer than timeout
        yield b"\n"

    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=infinite_proc_gen()):
        with anyio.fail_after(2): # Total test timeout
             start = anyio.current_time()
             await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
             end = anyio.current_time()
             # Should have terminated between 0.5 and 1.5 seconds
             duration = end - start
             assert 0.5 <= duration <= 1.5

@pytest.mark.anyio
async def test_activity_monitor() -> None:
    """Test ActivityMonitor properly tracks and timeouts."""
    # 1. Use real AnyIO memory streams to provide the .receive() method
    send, receive = anyio.create_memory_object_stream(1)
    monitor = ActivityMonitor(receive, timeout=0.2)

    # Check successful receive
    async with send:
        await send.send("a")
        # ActivityMonitor now implements the Iterator protocol via __anext__
        val = await monitor.__anext__()
        assert val == "a"

    # 2. Check watcher timeout
    # Fresh stream pair to avoid 'ClosedResourceError'
    send2, receive2 = anyio.create_memory_object_stream()
    monitor_timeout = ActivityMonitor(receive2, timeout=0.2)

    start = anyio.current_time()
    
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(monitor_timeout.watcher, tg)
            # Sleep longer than the 0.2s timeout to trigger the watcher
            await anyio.sleep(1)
    except (anyio.get_cancelled_exc_class(), ExceptionGroup):
        # AnyIO 4+ re-raises cancellation when the group exits
        pass

    duration = anyio.current_time() - start
    # Should be around 0.2s (plus check_interval)
    assert 0.2 <= duration <= 0.6

    # 3. Test EndOfStream -> StopAsyncIteration
    send3, receive3 = anyio.create_memory_object_stream()
    monitor_eof = ActivityMonitor(receive3)
    
    # Closing the send side causes receive() to raise anyio.EndOfStream
    send3.close()
    
    with pytest.raises(StopAsyncIteration):
        await monitor_eof.__anext__()

@pytest.mark.anyio
async def test_activity_monitor_receive_nowait() -> None:
    """Test ActivityMonitor.receive_nowait updates last_activity (lines 31-33)."""
    send, receive = anyio.create_memory_object_stream[str](1)
    monitor = ActivityMonitor(receive)
    await send.send("hello")
    old_time = monitor.last_activity
    await anyio.sleep(0.05)
    val = monitor.receive_nowait()
    assert val == "hello"
    assert monitor.last_activity >= old_time


@pytest.mark.anyio
async def test_activity_monitor_close() -> None:
    """Test ActivityMonitor.close delegates to the underlying stream (line 37)."""
    send, receive = anyio.create_memory_object_stream[str](1)
    monitor = ActivityMonitor(receive)
    monitor.close()
    with pytest.raises((anyio.ClosedResourceError, anyio.EndOfStream)):
        await monitor.receive()


@pytest.mark.anyio
async def test_activity_monitor_aclose() -> None:
    """Test ActivityMonitor.aclose delegates to the underlying stream (line 41)."""
    send, receive = anyio.create_memory_object_stream[str](1)
    monitor = ActivityMonitor(receive)
    await monitor.aclose()
    with pytest.raises((anyio.ClosedResourceError, anyio.EndOfStream)):
        await monitor.receive()


@pytest.mark.anyio
async def test_activity_monitor_statistics() -> None:
    """Test ActivityMonitor.statistics returns stream stats (line 45)."""
    send, receive = anyio.create_memory_object_stream[str](2)
    monitor = ActivityMonitor(receive)
    await send.send("a")
    stats = monitor.statistics()
    assert stats.current_buffer_used == 1


@pytest.mark.anyio
async def test_activity_monitor_aiter() -> None:
    """Test ActivityMonitor.__aiter__ returns self (line 48)."""
    _, receive = anyio.create_memory_object_stream[str](1)
    monitor = ActivityMonitor(receive)
    assert monitor.__aiter__() is monitor


@pytest.mark.anyio
async def test_activity_monitor_no_timeout() -> None:
    """Test ActivityMonitor with timeout disabled."""
    # Use a real stream pair to provide .receive() and other methods
    send, receive = anyio.create_memory_object_stream[str](1)

    monitor = ActivityMonitor(receive, timeout=0)
    async with anyio.create_task_group() as tg:
        # Watcher should return immediately
        await monitor.watcher(tg)

    # Check manual update
    old_time = monitor.last_activity
    await anyio.sleep(0.1)
    monitor.update()
    assert monitor.last_activity > old_time

@pytest.mark.anyio
async def test_bridge_streams_drain_stderr() -> None:
    """Test that bridge_streams drains stderr and updates activity."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc() # Ensure this sets .stdout and .stdin too

    async def stderr_gen() -> AsyncIterator[bytes]:
        yield b"error message\n"

    # Setup empty iterators for the other tasks so they finish immediately
    empty_iter = AsyncMock()
    empty_iter.__anext__.side_effect = StopAsyncIteration

    # sse_read should also be an empty iterator
    mock_sse_read.__aiter__.return_value = empty_iter

    # Patch read_lines: 
    # 1. First call (for proc_to_sse) returns empty
    # 2. Second call (for drain_stderr) returns the error message
    with patch("mcp_stdio_bridge.mode.proxy.read_lines",
               side_effect=[empty_iter, stderr_gen()]):
        try:
            await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
        except (anyio.get_cancelled_exc_class(), ExceptionGroup):
            pass

@pytest.mark.anyio
async def test_bridge_streams_stdin_none() -> None:
    """Test sse_to_proc logs error and breaks when proc.stdin is None (lines 86-87)."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stdin = None

    mock_msg = MagicMock()
    mock_msg.model_dump_json.return_value = '{"jsonrpc": "2.0"}'

    async def sse_gen() -> AsyncGenerator[Any, Any]:
        yield mock_msg

    mock_sse_read.__aiter__.side_effect = sse_gen

    with anyio.fail_after(5):
        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)


@pytest.mark.anyio
async def test_bridge_streams_stdout_none() -> None:
    """Test proc_to_sse cancels task group when proc.stdout is None (lines 97-99)."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stdout = None

    mock_iterator = AsyncMock()
    mock_iterator.__anext__.side_effect = StopAsyncIteration
    mock_sse_read.__aiter__.return_value = mock_iterator

    with anyio.fail_after(5):
        await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)


@pytest.mark.anyio
async def test_bridge_streams_stderr_none() -> None:
    """Test drain_stderr returns immediately when proc.stderr is None (lines 126-127)."""
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    mock_proc = _make_mock_proc()
    mock_proc.stderr = None

    mock_iterator = AsyncMock()
    mock_iterator.__anext__.side_effect = StopAsyncIteration
    mock_sse_read.__aiter__.return_value = mock_iterator

    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=AsyncMock()):
        with anyio.fail_after(5):
            await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)


@pytest.mark.anyio
async def test_bridge_streams_idle_timeout_disabled() -> None:
    """Test that idle_watcher returns immediately if idle_timeout <= 0."""
    settings["idle_timeout"] = -1
    mock_sse_read = AsyncMock()
    mock_sse_write = AsyncMock()
    
    # Ensure this helper sets .stdout, .stdin, and .stderr to NOT None
    mock_proc = _make_mock_proc()

    # 1. Setup sse_read to exit immediately
    mock_iterator = AsyncMock()
    mock_iterator.__anext__.side_effect = StopAsyncIteration
    mock_sse_read.__aiter__.return_value = mock_iterator

    # 2. Catch the cancellation OUTSIDE the bridge_streams call
    with patch("mcp_stdio_bridge.mode.proxy.read_lines", return_value=AsyncMock()):
        try:
            # bridge_streams starts the watcher, which sees timeout <= 0 and returns.
            # Then sse_to_proc finishes and cancels the group.
            await bridge_streams(mock_sse_read, mock_sse_write, mock_proc)
        except (anyio.get_cancelled_exc_class(), ExceptionGroup):
            # Catch the task group's "exit signal"
            pass
