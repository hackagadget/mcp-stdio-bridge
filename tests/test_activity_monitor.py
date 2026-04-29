# SPDX-License-Identifier: Unlicense
import pytest
import anyio
from typing import Any
from unittest.mock import MagicMock, AsyncMock
from mcp_stdio_bridge.activity_monitor import ActivityMonitor


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_activity_monitor_receive() -> None:
    send_stream, receive_stream = anyio.create_memory_object_stream[Any](1)
    monitor = ActivityMonitor(receive_stream, timeout=1.0)

    initial_activity = monitor.last_activity
    await anyio.sleep(0.1)

    await send_stream.send("test")
    val = await monitor.receive()

    assert val == "test"
    assert monitor.last_activity > initial_activity


@pytest.mark.anyio
async def test_activity_monitor_receive_nowait() -> None:
    send_stream, receive_stream = anyio.create_memory_object_stream[Any](1)
    monitor = ActivityMonitor(receive_stream, timeout=1.0)

    initial_activity = monitor.last_activity
    await anyio.sleep(0.1)

    await send_stream.send("test")
    val = monitor.receive_nowait()

    assert val == "test"
    assert monitor.last_activity > initial_activity


@pytest.mark.anyio
async def test_activity_monitor_close() -> None:
    mock_stream = MagicMock()
    monitor: ActivityMonitor[Any] = ActivityMonitor(mock_stream)
    monitor.close()
    assert mock_stream.close.called


@pytest.mark.anyio
async def test_activity_monitor_aclose() -> None:
    mock_stream = AsyncMock()
    monitor: ActivityMonitor[Any] = ActivityMonitor(mock_stream)
    await monitor.aclose()
    assert mock_stream.aclose.called


@pytest.mark.anyio
async def test_activity_monitor_statistics() -> None:
    mock_stream = MagicMock()
    monitor: ActivityMonitor[Any] = ActivityMonitor(mock_stream)
    monitor.statistics()
    assert mock_stream.statistics.called


@pytest.mark.anyio
async def test_activity_monitor_iteration() -> None:
    send_stream, receive_stream = anyio.create_memory_object_stream[Any](5)
    monitor = ActivityMonitor(receive_stream, timeout=1.0)

    await send_stream.send("a")
    await send_stream.send("b")
    await send_stream.aclose()

    results = []
    async for item in monitor:
        results.append(item)

    assert results == ["a", "b"]
    assert monitor.__aiter__() is monitor


@pytest.mark.anyio
async def test_activity_monitor_watcher_zero_timeout() -> None:
    mock_stream = MagicMock()
    monitor: ActivityMonitor[Any] = ActivityMonitor(mock_stream, timeout=0)

    async with anyio.create_task_group() as tg:
        # Should return immediately
        await monitor.watcher(tg)
        assert True
