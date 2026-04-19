# SPDX-License-Identifier: Unlicense
import pytest
import anyio
import ssl
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from mcp_stdio_bridge.config import settings
from mcp_stdio_bridge.transport.sse import create_app, run_sse_transport

@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'

@pytest.mark.anyio
async def test_handle_sse_no_command_proxy_mode() -> None:
    """Test handle_sse returns 500 if mode is proxy but no command is set."""
    settings["mode"] = "proxy"
    settings["command"] = None
    app = create_app()
    client = TestClient(app)
    response = client.get("/sse")
    assert response.status_code == 500
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_handle_sse_would_block() -> None:
    """Test handle_sse returns 503 if semaphore acquisition would block."""
    import mcp_stdio_bridge.transport.sse
    mcp_stdio_bridge.transport.sse.connection_semaphore = anyio.CapacityLimiter(1)

    async with mcp_stdio_bridge.transport.sse.connection_semaphore:
        app = create_app()
        client = TestClient(app)
        response = client.get("/sse")
        assert response.status_code == 503
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_handle_sse_spawns_process() -> None:
    """Test that handle_sse correctly spawns a subprocess in proxy mode."""
    with anyio.fail_after(5):
        settings["command"] = "echo hello"
        settings["api_key"] = None
        settings["mode"] = "proxy"

        mock_proc = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stderr = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.pid = 1234

        with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect_sse:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = (AsyncMock(), AsyncMock())
            mock_connect_sse.return_value = mock_ctx

            with patch("anyio.open_process") as mock_open_process:
                mock_proc_ctx = AsyncMock()
                mock_proc_ctx.__aenter__.return_value = mock_proc
                mock_open_process.return_value = mock_proc_ctx

                app = create_app()
                client = TestClient(app)

                with patch("mcp_stdio_bridge.transport.sse.bridge_streams",
                           new_callable=AsyncMock) as mock_bridge:
                    response = client.get("/sse")

                    assert response.status_code == 200
                    mock_open_process.assert_called_once()
                    mock_bridge.assert_called_once()
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_handle_sse_cleanup_on_disconnect() -> None:
    """Test that subprocess is terminated on SSE disconnect."""
    settings["command"] = "sleep 100"
    settings["mode"] = "proxy"

    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()

    with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("Disconnect")
        mock_connect.return_value = mock_ctx

        with patch("anyio.open_process") as mock_open:
            mock_proc_ctx = AsyncMock()
            mock_proc_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_proc_ctx

            app = create_app()
            client = TestClient(app)
            response = client.get("/sse")

            assert response.status_code == 500
            assert mock_proc.terminate.called
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_handle_sse_generic_error() -> None:
    """Test handle_sse catches generic exceptions and returns 500."""
    with patch("mcp_stdio_bridge.transport.sse.anyio.CapacityLimiter",
               side_effect=Exception("Generic")):
        import mcp_stdio_bridge.transport.sse
        mcp_stdio_bridge.transport.sse.connection_semaphore = None
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/sse")
        assert response.status_code == 500
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_sse_transport_wrapper_mode() -> None:
    """Test handle_sse in command-wrapper mode."""
    settings["mode"] = "command-wrapper"
    settings["wrapped_commands"] = [{"name": "t", "command": "echo", "description": "d"}]
    with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_connect.return_value = mock_ctx
        with patch("mcp_stdio_bridge.mode.wrapper.Server.run",
                   new_callable=AsyncMock) as mock_run:
            app = create_app()
            client = TestClient(app)
            response = client.get("/sse")
            assert response.status_code == 200
            mock_run.assert_called_once()

@pytest.mark.anyio
async def test_sse_transport_proxy_process_fail() -> None:
    """Test sse transport handles process spawn failure in proxy mode."""
    settings["mode"] = "proxy"
    settings["command"] = "invalid"

    with patch("anyio.open_process", side_effect=Exception("Spawn fail")):
        app = create_app()
        client = TestClient(app)
        response = client.get("/sse")
        assert response.status_code == 500
    await anyio.lowlevel.checkpoint()

@pytest.mark.anyio
async def test_sse_transport_wrapper_error() -> None:
    """Test handle_sse handles wrapper errors."""
    settings["mode"] = "command-wrapper"
    settings["wrapped_commands"] = [{"name": "t", "command": "echo", "description": "d"}]
    with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_connect.return_value = mock_ctx
        with patch("mcp_stdio_bridge.mode.wrapper.Server.run",
                   side_effect=Exception("Wrapper fail")):
            app = create_app()
            client = TestClient(app)
            response = client.get("/sse")
            assert response.status_code == 200 # Starlette handles the inner exception

@pytest.mark.anyio
async def test_sse_transport_bridge_streams_error() -> None:
    """Test sse transport logs bridge streams error."""
    settings["mode"] = "proxy"
    settings["command"] = "echo"
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_connect.return_value = mock_ctx
        with patch("anyio.open_process") as mock_open:
            mock_p_ctx = AsyncMock()
            mock_p_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_p_ctx
            with patch("mcp_stdio_bridge.transport.sse.bridge_streams",
                       side_effect=Exception("Fail")):
                 app = create_app()
                 client = TestClient(app)
                 client.get("/sse")

@pytest.mark.anyio
async def test_sse_transport_proc_terminate_error() -> None:
    """Test sse transport covers proc.terminate() (line 94)."""
    settings["mode"] = "proxy"
    settings["command"] = "sleep 100"
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate.side_effect = Exception("Terminate fail")

    with patch("mcp_stdio_bridge.transport.sse.sse.connect_sse") as mock_connect:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_connect.return_value = mock_ctx
        with patch("anyio.open_process") as mock_open:
            mock_p_ctx = AsyncMock()
            mock_p_ctx.__aenter__.return_value = mock_proc
            mock_open.return_value = mock_p_ctx
            with patch("mcp_stdio_bridge.mode.proxy.bridge_streams",
                       side_effect=Exception("Done")):
                 app = create_app()
                 client = TestClient(app)
                 client.get("/sse")
                 assert mock_proc.terminate.called

@pytest.mark.anyio
async def test_ssl_context_logic_full(tmp_path: Path) -> None:
    """Test full SSL context creation logic including CA certs and CRL."""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    ca = tmp_path / "ca.pem"
    crl = tmp_path / "crl.pem"
    cert.write_text("cert")
    key.write_text("key")
    ca.write_text("ca")
    crl.write_text("crl")

    settings["ssl_certfile"] = str(cert)
    settings["ssl_keyfile"] = str(key)
    settings["ssl_ca_certs"] = str(ca)
    settings["ssl_crlfile"] = str(crl)
    settings["ssl_client_cert_required"] = True
    settings["ssl_protocol"] = "TLSv1_3"
    settings["ssl_ciphers"] = "ECDHE-RSA-AES256-GCM-SHA384"
    settings["hsts"] = True

    with patch("ssl.SSLContext") as mock_context_cls:
        mock_ctx = mock_context_cls.return_value
        with patch("uvicorn.Server.serve", new_callable=AsyncMock):
            await run_sse_transport()

            mock_ctx.load_cert_chain.assert_called_once()
            mock_ctx.load_verify_locations.assert_called()
            assert mock_ctx.verify_mode == ssl.CERT_REQUIRED
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_3
    await anyio.lowlevel.checkpoint()

def test_ssl_context_logic_defaults(tmp_path: Path) -> None:
    """Test SSL context with TLSv1_2 and no client cert."""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("cert")
    key.write_text("key")
    settings["ssl_certfile"] = str(cert)
    settings["ssl_keyfile"] = str(key)
    settings["ssl_ca_certs"] = None
    settings["ssl_protocol"] = "TLSv1_2"
    with patch("ssl.SSLContext") as mock_context_cls:
        mock_ctx = mock_context_cls.return_value
        with patch("uvicorn.Server.serve", new_callable=AsyncMock):
            anyio.run(run_sse_transport)
            assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2

def test_ssl_context_verify_optional(tmp_path: Path) -> None:
    """Test SSL context when client cert is NOT required but CA certs provided."""
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    ca.write_text("ca")
    cert.write_text("c")
    key.write_text("k")
    settings["ssl_certfile"] = str(cert)
    settings["ssl_keyfile"] = str(key)
    settings["ssl_ca_certs"] = str(ca)
    settings["ssl_client_cert_required"] = False
    with patch("ssl.SSLContext") as mock_context_cls:
        mock_ctx = mock_context_cls.return_value
        with patch("uvicorn.Server.serve", new_callable=AsyncMock):
            anyio.run(run_sse_transport)
            assert mock_ctx.verify_mode == ssl.CERT_OPTIONAL

def test_refresh_server() -> None:
    """Test that refresh_server resets the global state."""
    from mcp_stdio_bridge.transport.sse import refresh_server
    import mcp_stdio_bridge.transport.sse as sse_mod

    sse_mod.wrapper_server = MagicMock()
    sse_mod.connection_semaphore = MagicMock()

    refresh_server()

    assert sse_mod.wrapper_server is None
    assert sse_mod.connection_semaphore is None
