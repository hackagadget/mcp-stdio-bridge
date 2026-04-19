import pytest
import anyio
from mcp_stdio_bridge.config import settings

@pytest.mark.anyio
async def test_wrapper_server_idle_timeout() -> None:
    """Test that wrapper server times out when idle."""
    settings["idle_timeout"] = 0.2
    from mcp_stdio_bridge.activity_monitor import ActivityMonitor
    # 1. Create a real (but empty) stream so the constructor doesn't fail
    _, receive_stream = anyio.create_memory_object_stream(1)
    monitor = ActivityMonitor(receive_stream, timeout=0.2)

    start = anyio.current_time()
    async with anyio.create_task_group() as tg:
        tg.start_soon(monitor.watcher, tg)
        await anyio.sleep(2)  # Watcher should cancel this before it completes

    duration = anyio.current_time() - start
    assert 0.2 <= duration <= 0.6
