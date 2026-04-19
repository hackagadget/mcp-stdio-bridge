import anyio
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectStreamStatistics
from typing import TypeVar
from typing_extensions import Self
from .logging_utils import logger

T = TypeVar("T")

class ActivityMonitor(MemoryObjectReceiveStream[T]):
    """
    Wraps an async iterable to monitor activity by updating a timestamp.
    Useful for implementing idle timeouts on stream-based transports.
    """
    def __init__(self, stream: MemoryObjectReceiveStream[T], timeout: float = 3600.0):
        self.stream = stream
        self.timeout = timeout
        self.update()

    def update(self) -> None:
        self.last_activity = anyio.current_time()

    async def receive(self) -> T:
        """The method MCP server.run actually calls."""
        val = await self.stream.receive()
        self.update()
        return val

    def receive_nowait(self) -> T:
        """Required for MemoryObjectReceiveStream."""
        val = self.stream.receive_nowait()
        self.update()
        return val

    def close(self) -> None:
        """Required synchronous close for MemoryObjectReceiveStream."""
        self.stream.close()

    async def aclose(self) -> None:
        """Required abstract method for ObjectReceiveStream."""
        await self.stream.aclose()

    def statistics(self) -> MemoryObjectStreamStatistics:
        """Required statistics method for MemoryObjectReceiveStream."""
        return self.stream.statistics()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    async def watcher(self, task_group: TaskGroup) -> None:
        """Watcher task that cancels the provided task group on timeout."""
        if self.timeout <= 0:
            return

        check_interval = max(0.1, min(10.0, self.timeout / 5.0))
        while True:
            await anyio.sleep(check_interval)
            if anyio.current_time() - self.last_activity > self.timeout:
                logger.warning(f"Session idle for > {self.timeout}s. Terminating.")
                task_group.cancel_scope.cancel()
                break
