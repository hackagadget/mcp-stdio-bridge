# SPDX-License-Identifier: Unlicense
import yaml
import json
import jsonschema
import pytest
from pathlib import Path
from unittest.mock import patch
from mcp_stdio_bridge.config import settings, finalize_settings, parse_args

def test_config_schema_validation() -> None:
    """Validate config.example.yaml against schema.json."""
    root_dir = Path(__file__).parent.parent
    schema_path = root_dir / "schema.json"
    example_config_path = root_dir / "config.example.yaml"

    with open(schema_path, "r") as f:
        schema = json.load(f)

    with open(example_config_path, "r") as f:
        config = yaml.safe_load(f)

    jsonschema.validate(instance=config, schema=schema)

def test_main_config_loading(tmp_path: Path) -> None:
    """Test loading configuration from a YAML file."""
    config_file = tmp_path / "config.yaml"
    config_data = {
        "host": "127.0.0.1",
        "port": 9000,
        "command": "test-cmd",
        "api_key": "test-key"
    }
    config_file.write_text(yaml.dump(config_data))

    with patch("sys.argv", ["mcp-stdio-bridge", "--config", str(config_file)]):
        with patch("anyio.run"):
            from mcp_stdio_bridge.main import main as cli_main
            settings["command"] = None
            cli_main()
            assert settings["command"] == "test-cmd"

def test_config_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that --version flag prints version and exits."""
    from mcp_stdio_bridge import __version__
    with patch("sys.argv", ["mcp-stdio-bridge", "--version"]):
        with pytest.raises(SystemExit) as e:
            parse_args()
        assert e.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out

def test_config_search_hierarchy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test configuration loading hierarchy (Home directory)."""
    config_data = {"command": "home-cmd"}
    home_config = tmp_path / ".mcp-stdio-bridge.yaml"
    home_config.write_text(yaml.dump(config_data))

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["mcp-stdio-bridge"]):
        with patch("anyio.run"):
            from mcp_stdio_bridge.main import main as cli_main
            settings["command"] = None
            cli_main()
            assert settings["command"] == "home-cmd"

def test_config_load_exception(capsys: pytest.CaptureFixture[str]) -> None:
    """Test load_config handles exceptions gracefully and prints error to stderr."""
    from mcp_stdio_bridge.config import load_config
    with patch("mcp_stdio_bridge.config.os.path.exists", return_value=True):
        with patch("mcp_stdio_bridge.config.open", side_effect=RuntimeError("Fail")):
             assert load_config("some.yaml") == {}
             captured = capsys.readouterr()
             assert "Error loading config from some.yaml: Fail" in captured.err

def test_get_env_overrides_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test environment variable type conversion (bool, int, list)."""
    from mcp_stdio_bridge.config import get_env_overrides
    monkeypatch.setenv("MCP_VERBOSE", "true")
    monkeypatch.setenv("MCP_PORT", "9000")
    monkeypatch.setenv("MCP_ENV_DENYLIST", "A, B, C")

    overrides = get_env_overrides()
    assert overrides["verbose"] is True
    assert overrides["port"] == 9000
    assert overrides["env_denylist"] == ["A", "B", "C"]

    # Test string override (line 76)
    monkeypatch.setenv("MCP_COMMAND", "custom-cmd")
    overrides = get_env_overrides()
    assert overrides["command"] == "custom-cmd"

def test_get_masked_settings() -> None:
    """Test that sensitive settings are masked."""
    from mcp_stdio_bridge.config import get_masked_settings, settings
    settings["api_key"] = "secret"
    settings["ssl_keyfile_password"] = "password"  # noqa: S105
    masked = get_masked_settings()
    assert masked["api_key"] == "********"
    assert masked["ssl_keyfile_password"] == "********"  # noqa: S105

def test_prepare_env_allowlist_denylist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test environment scrubbing logic (allowlist and denylist)."""
    from mcp_stdio_bridge.config import prepare_env, settings
    monkeypatch.setenv("ALLOWED", "yes")
    monkeypatch.setenv("FORBIDDEN", "no")
    monkeypatch.setenv("MCP_API_KEY", "key")

    # Test Denylist (default)
    settings["env_allowlist"] = None
    settings["env_denylist"] = ["FORBIDDEN", "MCP_API_KEY"]
    env = prepare_env()
    assert "ALLOWED" in env
    assert "FORBIDDEN" not in env
    assert "MCP_API_KEY" not in env

    # Test Allowlist
    settings["env_allowlist"] = ["ALLOWED"]
    env = prepare_env()
    assert "ALLOWED" in env
    assert "FORBIDDEN" not in env
    assert "MCP_API_KEY" not in env

def test_config_cli_overrides() -> None:
    """Test that CLI arguments correctly override config file settings."""
    with patch("sys.argv",
               ["mcp-stdio-bridge", "--command", "cli-cmd", "--port", "9999", "--mode",
                "command-wrapper"]):
        with patch("mcp_stdio_bridge.config.load_config",
                   return_value={"command": "file-cmd", "port": 8000}):
            finalize_settings(parse_args())
            assert settings["command"] == "cli-cmd"
            assert settings["port"] == 9999
            assert settings["mode"] == "command-wrapper"

def test_config_new_cli_flags() -> None:
    """Test the newly added CLI flags for SSL, security, and environment."""
    test_args = [
        "mcp-stdio-bridge",
        "--ssl-keyfile", "key.pem",
        "--ssl-certfile", "cert.pem",
        "--ssl-protocol", "TLSv1_3",
        "--ssl-client-cert-required",
        "--hsts",
        "--no-security-headers",
        "--cors-origins", "http://localhost", "https://example.com",
        "--max-message-size", "2097152",
        "--idle-timeout", "7200",
        "--env-allowlist", "PATH", "HOME",
        "--env-denylist", "SECRET_KEY"
    ]
    with patch("sys.argv", test_args):
        finalize_settings(parse_args())
        assert settings["ssl_keyfile"] == "key.pem"
        assert settings["ssl_certfile"] == "cert.pem"
        assert settings["ssl_protocol"] == "TLSv1_3"
        assert settings["ssl_client_cert_required"] is True
        assert settings["hsts"] is True
        assert settings["security_headers"] is False
        assert settings["cors_origins"] == ["http://localhost", "https://example.com"]
        assert settings["max_message_size"] == 2097152
        assert settings["idle_timeout"] == 7200
        assert settings["env_allowlist"] == ["PATH", "HOME"]
        assert settings["env_denylist"] == ["SECRET_KEY"]

def test_config_no_spurious_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that no warnings are printed in stdio mode if options are not provided."""
    test_args = ["mcp-stdio-bridge", "--transport", "stdio"]
    with patch("sys.argv", test_args):
        finalize_settings(parse_args())
        captured = capsys.readouterr()
        assert "Warning" not in captured.err

def test_config_validation_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that mutually exclusive or irrelevant options trigger warnings on stderr."""
    # 1. Test SSE options with Stdio transport
    test_args = ["mcp-stdio-bridge", "--transport", "stdio", "--port", "9000",
                 "--api-key", "secret"]
    with patch("sys.argv", test_args):
        finalize_settings(parse_args())
        captured = capsys.readouterr()
        assert "Warning: Option --port is ignored in Stdio transport mode." in captured.err
        assert "Warning: Option --api-key is ignored in Stdio transport mode." in captured.err

    # 2. Test Allowlist and Denylist precedence warning
    test_args = ["mcp-stdio-bridge", "--env-allowlist", "PATH", "--env-denylist", "SECRET"]
    with patch("sys.argv", test_args):
        finalize_settings(parse_args())
        captured = capsys.readouterr()
        assert "Warning: Both env_allowlist and env_denylist are set. env_allowlist will " \
               "take precedence." in captured.err

def test_reload_settings_returns_false_before_finalize() -> None:
    """reload_settings() returns False when _last_args is None (before finalize_settings
    has been called)."""
    from mcp_stdio_bridge.config import reload_settings
    with patch("mcp_stdio_bridge.config._last_args", None):
        assert reload_settings() is False

def test_reload_settings_returns_true_after_finalize() -> None:
    """reload_settings() returns True and re-applies settings after finalize_settings has
    run."""
    from mcp_stdio_bridge.config import reload_settings
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo"]):
        finalize_settings(parse_args())
    assert reload_settings() is True

def test_get_config_files_after_finalize(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """get_config_files() returns home config and local config paths after
    finalize_settings()."""
    from mcp_stdio_bridge.config import get_config_files
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge"]):
        finalize_settings(parse_args())
    files = get_config_files()
    assert isinstance(files, list)
    assert str(tmp_path / ".mcp-stdio-bridge.yaml") in files
    assert str(tmp_path / "config.yaml") in files

def test_get_config_files_includes_explicit_config(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """get_config_files() includes the --config path when one is explicitly provided."""
    from mcp_stdio_bridge.config import get_config_files
    explicit = str(tmp_path / "custom.yaml")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge", "--config", explicit]):
        finalize_settings(parse_args())
    assert explicit in get_config_files()
