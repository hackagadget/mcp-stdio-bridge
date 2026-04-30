# SPDX-License-Identifier: Unlicense
import pytest
from mcp_stdio_bridge.utils import ExponentialBackoff

@pytest.mark.anyio
async def test_backoff_math() -> None:
    settings = {
        "max_retries": 3,
        "retry_delay": 0.1,
        "retry_max_delay": 0.5,
        "retry_multiplier": 2.0
    }
    backoff = ExponentialBackoff(settings)
    
    assert backoff.attempts == 0
    assert backoff.get_delay() == 0.0
    
    # First attempt (wait increments attempts BEFORE calculating delay for the NEXT one)
    # Actually wait increments attempts and then sleeps for the delay calculated for THIS attempt.
    # get_delay uses (attempts - 1)
    
    # 0 -> 1: delay 0.0
    assert await backoff.wait() is True
    assert backoff.attempts == 1
    
    # 1 -> 2: delay 0.1
    assert backoff.get_delay() == 0.1
    assert await backoff.wait() is True
    assert backoff.attempts == 2
    
    # 2 -> 3: delay 0.2
    assert backoff.get_delay() == 0.2
    assert await backoff.wait() is True
    assert backoff.attempts == 3
    
    # Max retries reached
    assert backoff.can_retry() is False
    assert await backoff.wait() is False

@pytest.mark.anyio
async def test_backoff_max_delay() -> None:
    settings = {
        "max_retries": 5,
        "retry_delay": 0.1,
        "retry_max_delay": 0.15,
        "retry_multiplier": 2.0
    }
    backoff = ExponentialBackoff(settings)
    
    await backoff.wait() # att 1, delay 0.0
    await backoff.wait() # att 2, delay 0.1
    assert backoff.get_delay() == 0.15 # capped at 0.15 instead of 0.2

def test_backoff_reset() -> None:
    backoff = ExponentialBackoff({"max_retries": 3})
    backoff.attempts = 2
    backoff.reset()
    assert backoff.attempts == 0
    assert backoff.get_delay() == 0.0


@pytest.mark.anyio
async def test_stdio_retry_loop() -> None:
    """Test that Stdio transport correctly retries a failing command."""
    from mcp_stdio_bridge.transport.stdio import run_stdio_transport
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch, MagicMock, AsyncMock

    settings["mode"] = "proxy"
    settings["command"] = "fail-then-win"
    settings["max_retries"] = 2
    settings["retry_delay"] = 0.01  # Keep tests fast

    call_count = 0

    async def mock_open_process(*args, **kwargs):  # type: ignore
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Subprocess failed to start")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.pid = 1234
        mock_proc.stdin = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stderr = AsyncMock()

        class MockCtx:
            async def __aenter__(self) -> MagicMock:
                return mock_proc

            async def __aexit__(self, *args: object) -> None:
                pass

        return MockCtx()

    with patch("anyio.open_process", side_effect=mock_open_process):
        await run_stdio_transport()
        assert call_count == 3


@pytest.mark.anyio
async def test_sse_retry_backoff() -> None:
    """Test that SSE proxy throttles new connections after a subprocess crash."""
    import mcp_stdio_bridge.transport.sse_proxy as sse_proxy
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch, MagicMock, AsyncMock

    settings["mode"] = "proxy"
    settings["command"] = "crash-on-start"
    settings["max_retries"] = 5
    settings["retry_delay"] = 0.5
    settings["api_key"] = None

    # Reset global state in sse_proxy
    sse_proxy.retry_manager = None
    sse_proxy.connection_semaphore = None

    # Mock subprocess to crash immediately (returncode=1)
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.wait = AsyncMock(return_value=1)
    mock_proc.pid = 999
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    class MockCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_proc

        async def __aexit__(self, *args: object) -> None:
            pass

    async def mock_receive() -> dict[str, str]:
        return {"type": "http.request"}

    async def mock_send(msg: object) -> None:
        pass

    # Track sleep calls
    with (
        patch("mcp_stdio_bridge.transport.sse_proxy.anyio.open_process", return_value=MockCtx()),
        patch("mcp_stdio_bridge.transport.sse_proxy.bridge_streams", AsyncMock()),
        patch("mcp_stdio_bridge.transport.sse_proxy.anyio.sleep", AsyncMock()) as mock_sleep,
    ):
        # First attempt: no delay
        await sse_proxy.proxy_asgi_app(
            {"type": "http", "method": "GET", "path": "/sse"}, mock_receive, mock_send
        )
        assert sse_proxy.retry_manager is not None
        assert sse_proxy.retry_manager.attempts == 1
        assert mock_sleep.call_count == 0

        # Second attempt: should delay by 0.5s
        await sse_proxy.proxy_asgi_app(
            {"type": "http", "method": "GET", "path": "/sse"}, mock_receive, mock_send
        )
        assert sse_proxy.retry_manager is not None
        assert sse_proxy.retry_manager.attempts == 2
        mock_sleep.assert_called_with(0.5)


@pytest.mark.anyio
async def test_stdio_retry_limit_reached() -> None:
    """Test that Stdio transport gives up after max retries."""
    from mcp_stdio_bridge.transport.stdio import run_stdio_transport
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch

    settings["mode"] = "proxy"
    settings["command"] = "always-fails"
    settings["max_retries"] = 1
    settings["retry_delay"] = 0.01

    with (
        patch("anyio.open_process", side_effect=Exception("Permanent failure")),
        patch("mcp_stdio_bridge.transport.stdio.logger") as mock_logger,
    ):
        await run_stdio_transport()
        assert any("Giving up" in call[0][0] for call in mock_logger.error.call_args_list)


@pytest.mark.anyio
async def test_stdio_clean_exit() -> None:
    """Test that Stdio transport stops retrying after a clean exit (returncode 0)."""
    from mcp_stdio_bridge.transport.stdio import run_stdio_transport
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch, MagicMock, AsyncMock

    settings["mode"] = "proxy"
    settings["command"] = "clean-exit"
    settings["max_retries"] = 5

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 777
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    class MockCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_proc

        async def __aexit__(self, *args: object) -> None:
            pass

    with patch("anyio.open_process", return_value=MockCtx()) as mock_open:
        await run_stdio_transport()
        assert mock_open.call_count == 1


@pytest.mark.anyio
async def test_stdio_retry_on_crash() -> None:
    """Test that Stdio transport retries when subprocess exits with non-zero code."""
    from mcp_stdio_bridge.transport.stdio import run_stdio_transport
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch, MagicMock, AsyncMock

    settings["mode"] = "proxy"
    settings["command"] = "crash-on-exit"
    settings["max_retries"] = 1
    settings["retry_delay"] = 0.01

    call_count = 0

    async def mock_open_process(*args, **kwargs):  # type: ignore
        nonlocal call_count
        call_count += 1
        mock_proc = MagicMock()
        # First call: crash with 1. Second call: success with 0.
        mock_proc.returncode = 1 if call_count == 1 else 0
        mock_proc.wait = AsyncMock()
        mock_proc.pid = 4321
        mock_proc.stdin = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stderr = AsyncMock()

        class MockCtx:
            async def __aenter__(self) -> MagicMock:
                return mock_proc

            async def __aexit__(self, *args: object) -> None:
                pass

        return MockCtx()

    with patch("anyio.open_process", side_effect=mock_open_process) as mock_open:
        await run_stdio_transport()
        assert mock_open.call_count == 2


@pytest.mark.anyio
async def test_sse_retry_on_bridge_error() -> None:
    """Test that SSE proxy tracks crashes when bridge_streams fails."""
    import mcp_stdio_bridge.transport.sse_proxy as sse_proxy
    from mcp_stdio_bridge.config import settings
    from mcp_stdio_bridge.utils import ExponentialBackoff
    from unittest.mock import patch, MagicMock, AsyncMock

    settings["mode"] = "proxy"
    settings["command"] = "bridge-fail"
    settings["max_retries"] = 5
    settings["api_key"] = None

    # Ensure retry_manager is initialized
    sse_proxy.retry_manager = ExponentialBackoff(settings)
    sse_proxy.connection_semaphore = None

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()

    class MockCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_proc

        async def __aexit__(self, *args: object) -> None:
            pass

    async def mock_receive() -> dict[str, str]:
        return {"type": "http.request"}

    with (
        patch("mcp_stdio_bridge.transport.sse_proxy.anyio.open_process", return_value=MockCtx()),
        patch(
            "mcp_stdio_bridge.transport.sse_proxy.bridge_streams",
            side_effect=Exception("Bridge Explosion"),
        ),
        patch("mcp_stdio_bridge.transport.sse_proxy.logger") as mock_logger,
    ):
        await sse_proxy.proxy_asgi_app(
            {"type": "http", "method": "GET", "path": "/sse"}, mock_receive, AsyncMock()
        )
        assert sse_proxy.retry_manager.attempts == 1
        assert any("Bridge error" in call[0][0] for call in mock_logger.error.call_args_list)


@pytest.mark.anyio
async def test_stdio_retry_disabled() -> None:
    """Test that Stdio transport does not retry when max_retries is 0."""
    from mcp_stdio_bridge.transport.stdio import run_stdio_transport
    from mcp_stdio_bridge.config import settings
    from unittest.mock import patch

    settings["mode"] = "proxy"
    settings["command"] = "no-retry"
    settings["max_retries"] = 0

    with (
        patch("anyio.open_process", side_effect=Exception("Single failure")),
        patch("mcp_stdio_bridge.transport.stdio.logger") as mock_logger,
    ):
        await run_stdio_transport()
        # Should say giving up immediately
        assert any("Giving up" in call[0][0] for call in mock_logger.error.call_args_list)


@pytest.mark.anyio
async def test_run_proxy_transport_basic() -> None:
    """Test run_proxy_transport by mocking uvicorn.Server."""
    from mcp_stdio_bridge.transport.sse_proxy import run_proxy_transport
    from unittest.mock import patch, MagicMock, AsyncMock

    mock_server = MagicMock()
    mock_server.serve = AsyncMock()

    with patch("uvicorn.Server", return_value=mock_server):
        await run_proxy_transport()
        assert mock_server.serve.called


def test_backoff_disabled() -> None:
    """Test that ExponentialBackoff handles max_retries <= 0 correctly."""
    backoff = ExponentialBackoff({"max_retries": 0})
    assert backoff.can_retry() is False
    
    backoff_neg = ExponentialBackoff({"max_retries": -1})
    assert backoff_neg.can_retry() is False


@pytest.mark.anyio
async def test_handle_proxy_sse_global_crash() -> None:
    """Test the outer exception handler in _handle_proxy_sse."""
    import mcp_stdio_bridge.transport.sse_proxy as sse_proxy
    from unittest.mock import patch, AsyncMock

    # Trigger exception at the very beginning of the function
    with (
        patch("anyio.CapacityLimiter", side_effect=Exception("Global SSE Crash")),
        patch("mcp_stdio_bridge.transport.sse_proxy.logger") as mock_logger,
    ):
        sse_proxy.connection_semaphore = None  # Force re-init
        await sse_proxy._handle_proxy_sse({}, AsyncMock(), AsyncMock())
        assert any(
            "Crash: Global SSE Crash" in call[0][0]
            for call in mock_logger.error.call_args_list
        )
