# SPDX-License-Identifier: Unlicense
import yaml
import jsonschema
import pytest
import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch
from mcp_stdio_bridge.config import settings, finalize_settings, parse_args


def test_config_schema_validation() -> None:
    """Validate config.example.yaml against the bundled schema."""
    from mcp_stdio_bridge.config import _load_schema

    example_config_path = Path(__file__).parent.parent / "config.example.yaml"

    schema = _load_schema()

    with open(example_config_path, "r") as f:
        config = yaml.safe_load(f)

    jsonschema.validate(instance=config, schema=schema)


def test_main_config_loading(tmp_path: Path) -> None:
    """Test loading configuration from a YAML file."""
    config_file = tmp_path / "config.yaml"
    config_data = {"host": "127.0.0.1", "port": 9000, "command": "test-cmd", "api_key": "test-key"}
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
    with patch(
        "sys.argv",
        ["mcp-stdio-bridge", "--command", "cli-cmd", "--port", "9999", "--mode", "command-wrapper"],
    ):
        with patch(
            "mcp_stdio_bridge.config.load_config",
            return_value={"command": "file-cmd", "port": 8000},
        ):
            finalize_settings(parse_args())
            assert settings["command"] == "cli-cmd"
            assert settings["port"] == 9999
            assert settings["mode"] == "command-wrapper"


def test_config_new_cli_flags() -> None:
    """Test the newly added CLI flags for SSL, security, and environment."""
    test_args = [
        "mcp-stdio-bridge",
        "--ssl-keyfile",
        "key.pem",
        "--ssl-certfile",
        "cert.pem",
        "--ssl-protocol",
        "TLSv1_3",
        "--ssl-client-cert-required",
        "--hsts",
        "--no-security-headers",
        "--cors-origins",
        "http://localhost",
        "https://example.com",
        "--max-message-size",
        "2097152",
        "--idle-timeout",
        "7200",
        "--env-allowlist",
        "PATH",
        "HOME",
        "--env-denylist",
        "SECRET_KEY",
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
    test_args = [
        "mcp-stdio-bridge",
        "--transport",
        "stdio",
        "--port",
        "9000",
        "--api-key",
        "secret",
    ]
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
        assert (
            "Warning: Both env_allowlist and env_denylist are set. env_allowlist will "
            "take precedence." in captured.err
        )


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


def test_get_config_files_after_finalize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_get_config_files_includes_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_config_files() includes the --config path when one is explicitly provided."""
    from mcp_stdio_bridge.config import get_config_files

    explicit = str(tmp_path / "custom.yaml")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge", "--config", explicit]):
        finalize_settings(parse_args())
    assert explicit in get_config_files()


# ---------------------------------------------------------------------------
# generate_config
# ---------------------------------------------------------------------------


def test_generate_config_includes_non_default_values() -> None:
    """Non-default CLI values appear in the generated YAML."""
    from mcp_stdio_bridge.config import generate_config
    import argparse

    args = argparse.Namespace(
        config=None,
        check_config=False,
        warnings_as_errors=False,
        generate_api_key=False,
        generate_config=True,
        mode=None,
        transport=None,
        host=None,
        port=9000,
        command="npx mcp-server",
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    output = generate_config(args)
    data = yaml.safe_load(output)
    assert data["command"] == "npx mcp-server"
    assert data["port"] == 9000


def test_generate_config_omits_default_values() -> None:
    """Values equal to their defaults are not written to the output."""
    from mcp_stdio_bridge.config import generate_config
    import argparse

    args = argparse.Namespace(
        config=None,
        check_config=False,
        warnings_as_errors=False,
        generate_api_key=False,
        generate_config=True,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command="echo",
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    output = generate_config(args)
    data = yaml.safe_load(output)
    # verbose=False is the default — must not appear
    assert "verbose" not in data
    # port is absent (None → filtered) — must not appear
    assert "port" not in data


def test_generate_config_embeds_api_key() -> None:
    """When --generate-api-key is also set, the key appears in the YAML output."""
    from mcp_stdio_bridge.config import generate_config
    import argparse

    args = argparse.Namespace(
        config=None,
        check_config=False,
        warnings_as_errors=False,
        generate_api_key=True,
        generate_config=True,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command="echo",
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    output = generate_config(args)
    data = yaml.safe_load(output)
    assert "api_key" in data
    assert len(data["api_key"]) >= 32


def test_generate_config_excludes_cli_only_keys() -> None:
    """Utility flags like check_config and warnings_as_errors are not emitted."""
    from mcp_stdio_bridge.config import generate_config
    import argparse

    args = argparse.Namespace(
        config=None,
        check_config=True,
        warnings_as_errors=True,
        generate_api_key=False,
        generate_config=True,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command="echo",
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    output = generate_config(args)
    data = yaml.safe_load(output)
    for key in ("check_config", "warnings_as_errors", "generate_api_key", "generate_config"):
        assert key not in data


def test_generate_config_has_header_comment() -> None:
    """Output starts with a comment identifying the generator."""
    from mcp_stdio_bridge.config import generate_config
    import argparse

    args = argparse.Namespace(
        config=None,
        check_config=False,
        warnings_as_errors=False,
        generate_api_key=False,
        generate_config=True,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command="echo",
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    assert generate_config(args).startswith("# Generated by mcp-stdio-bridge")


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------


def test_validate_settings_proxy_missing_command() -> None:
    """proxy mode without command is an error."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "mode": "proxy", "command": None}
    errors, warnings = validate_settings(final)
    assert any("proxy" in e and "command" in e for e in errors)
    assert warnings == []


def test_validate_settings_wrapper_missing_commands() -> None:
    """command-wrapper mode without wrapped_commands is an error."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "mode": "command-wrapper", "wrapped_commands": []}
    errors, warnings = validate_settings(final)
    assert any("command-wrapper" in e for e in errors)
    assert warnings == []


def test_validate_settings_ssl_keyfile_without_certfile() -> None:
    """ssl_keyfile set without ssl_certfile is an error."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "command": "echo", "ssl_keyfile": "key.pem", "ssl_certfile": None}
    errors, _ = validate_settings(final)
    assert any("ssl_keyfile" in e and "ssl_certfile" in e for e in errors)


def test_validate_settings_ssl_certfile_without_keyfile() -> None:
    """ssl_certfile set without ssl_keyfile is an error."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "command": "echo", "ssl_keyfile": None, "ssl_certfile": "cert.pem"}
    errors, _ = validate_settings(final)
    assert any("ssl_certfile" in e and "ssl_keyfile" in e for e in errors)


def test_validate_settings_stdio_sse_key_warning() -> None:
    """SSE-only key set while transport is stdio produces a warning."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "command": "echo", "transport": "stdio", "api_key": "secret"}
    errors, warnings = validate_settings(final)
    assert errors == []
    assert any("api_key" in w for w in warnings)


def test_validate_settings_env_list_conflict_warning() -> None:
    """Both env_allowlist and a custom env_denylist set produces a warning."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {
        **DEFAULT_SETTINGS,
        "command": "echo",
        "env_allowlist": ["PATH"],
        "env_denylist": ["SECRET"],
    }
    errors, warnings = validate_settings(final)
    assert errors == []
    assert any("env_allowlist" in w for w in warnings)


def test_validate_settings_valid_proxy() -> None:
    """A properly configured proxy has no errors or warnings."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "command": "npx mcp-server"}
    errors, warnings = validate_settings(final)
    assert errors == []
    assert warnings == []


def test_validate_settings_valid_wrapper() -> None:
    """A properly configured command-wrapper has no errors or warnings."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {
        **DEFAULT_SETTINGS,
        "mode": "command-wrapper",
        "wrapped_commands": [{"name": "t", "description": "d", "command": "echo"}],
    }
    errors, warnings = validate_settings(final)
    assert errors == []
    assert warnings == []


def test_validate_settings_daemonize_with_stdio_is_error() -> None:
    """daemonize=True combined with stdio transport is a configuration error."""
    from mcp_stdio_bridge.config import validate_settings, DEFAULT_SETTINGS

    final = {**DEFAULT_SETTINGS, "command": "echo", "transport": "stdio", "daemonize": True}
    errors, _ = validate_settings(final)
    assert any("daemonize" in e for e in errors)


# ---------------------------------------------------------------------------
# check_config
# ---------------------------------------------------------------------------


def _make_args(**kwargs: Any) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for check_config tests."""
    import argparse

    defaults = dict(
        config=None,
        check_config=True,
        warnings_as_errors=False,
        generate_api_key=False,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command=None,
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_check_config_ok_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No config files + command via CLI exits 0 and prints 'configuration ok'."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _make_args(command="echo")
    assert check_config(args, False) == 0  # type: ignore[arg-type]
    assert "configuration ok" in capsys.readouterr().err


def test_check_config_ok_with_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Valid config file exits 0 and includes the file path in the output."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump({"command": "echo"}))
    args = _make_args()
    assert check_config(args, False) == 0  # type: ignore[arg-type]
    out = capsys.readouterr().err
    assert "configuration ok" in out
    assert str(cfg) in out


def test_check_config_yaml_parse_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A YAML parse error exits 1 and reports the file."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "config.yaml"
    bad.write_text("key: [unclosed")
    args = _make_args()
    assert check_config(args, False) == 1  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert "[error]" in err
    assert "configuration has errors" in err


def test_check_config_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown key in the config file exits 1 with a schema error."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "config.yaml"
    bad.write_text(yaml.dump({"command": "echo", "unknown_key_xyz": True}))
    args = _make_args()
    assert check_config(args, False) == 1  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert "[error]" in err
    assert "configuration has errors" in err


def test_check_config_semantic_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """proxy mode with no command is a semantic error that exits 1."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _make_args()  # no command → proxy with no command
    assert check_config(args, False) == 1  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert "[error]" in err


def test_check_config_warning_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A warning alone exits 0 and prints [warn]."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    # stdio transport + api_key set → warning
    args = _make_args(command="echo", transport="stdio", api_key="secret")
    assert check_config(args, False) == 0  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert "[warn]" in err
    assert "configuration ok" in err


def test_check_config_warnings_as_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With warnings_as_errors=True a warning promotes to [error] and exits 1."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _make_args(command="echo", transport="stdio", api_key="secret")
    assert check_config(args, True) == 1  # type: ignore[arg-type]
    err = capsys.readouterr().err
    assert "[error]" in err
    assert "configuration has errors" in err


def test_check_config_explicit_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--config pointing to a valid file is loaded and reported."""
    from mcp_stdio_bridge.config import check_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "custom.yaml"
    explicit.write_text(yaml.dump({"command": "echo"}))
    args = _make_args(config=str(explicit))
    assert check_config(args, False) == 0  # type: ignore[arg-type]
    assert str(explicit) in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CLI dispatch for --generate-config
# ---------------------------------------------------------------------------


def test_main_generate_config_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--generate-config prints YAML to stdout and exits 0 without starting the bridge."""
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge", "--generate-config", "--command", "echo"]):
        with patch("anyio.run") as mock_run:
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 0
            mock_run.assert_not_called()
    data = yaml.safe_load(capsys.readouterr().out)
    assert data["command"] == "echo"


def test_main_generate_config_with_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--generate-config --generate-api-key embeds the key in YAML instead of printing it."""
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch(
        "sys.argv",
        ["mcp-stdio-bridge", "--generate-config", "--generate-api-key", "--command", "echo"],
    ):
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 0
    out = capsys.readouterr().out
    data = yaml.safe_load(out)
    assert "api_key" in data
    assert len(data["api_key"]) >= 32
    # Key must not also appear as a bare line (it should only be in the YAML)
    assert data["api_key"] in out


def test_main_generate_api_key_alone_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """--generate-api-key without --generate-config still just prints a bare key."""
    from mcp_stdio_bridge.main import main as cli_main

    with patch("sys.argv", ["mcp-stdio-bridge", "--generate-api-key"]):
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    # Should be a single token with no YAML structure
    assert "\n" not in out
    assert ":" not in out
    assert len(out) >= 32


# ---------------------------------------------------------------------------
# CLI dispatch for --check-config and --warnings-as-errors
# ---------------------------------------------------------------------------


def test_main_check_config_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--check-config with a valid config exits 0 before starting the bridge."""
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge", "--check-config", "--command", "echo"]):
        with patch("anyio.run") as mock_run:
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 0
            mock_run.assert_not_called()


def test_main_check_config_exits_one_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--check-config with a missing command exits 1."""
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["mcp-stdio-bridge", "--check-config"]):
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 1


def test_main_warnings_as_errors_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--warnings-as-errors with a warning condition exits 1."""
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch(
        "sys.argv",
        [
            "mcp-stdio-bridge",
            "--check-config",
            "--warnings-as-errors",
            "--command",
            "echo",
            "--transport",
            "stdio",
            "--api-key",
            "secret",
        ],
    ):
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# generate_client_config
# ---------------------------------------------------------------------------


def _client_args(**kwargs: Any) -> argparse.Namespace:
    """Build a minimal Namespace for generate_client_config tests."""
    import argparse

    defaults = dict(
        config=None,
        check_config=False,
        warnings_as_errors=False,
        generate_api_key=False,
        generate_config=False,
        generate_client_config=None,
        output=None,
        mode=None,
        transport=None,
        host=None,
        port=None,
        command=None,
        api_key=None,
        max_connections=None,
        max_message_size=None,
        verbose=False,
        logging_level=None,
        logging_config=None,
        ssl_keyfile=None,
        ssl_certfile=None,
        ssl_keyfile_password=None,
        ssl_ca_certs=None,
        ssl_crlfile=None,
        ssl_client_cert_required=False,
        ssl_protocol=None,
        ssl_ciphers=None,
        hsts=None,
        security_headers=None,
        cors_origins=None,
        idle_timeout=None,
        rate_limit_requests=None,
        rate_limit_window=None,
        env_allowlist=None,
        env_denylist=None,
        watch_config=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_generate_client_config_stdio_claude_desktop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdio transport → claude-desktop gets command/args entry under mcpServers."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="stdio")
    result = json.loads(generate_client_config(args, "claude-desktop"))
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server["command"] == "mcp-stdio-bridge"
    assert "url" not in server


def test_generate_client_config_stdio_includes_config_arg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When --config is given, stdio entry includes --config in args."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = str(tmp_path / "config.yaml")
    args = _client_args(transport="stdio", config=cfg)
    result = json.loads(generate_client_config(args, "claude-code"))
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert "--config" in server.get("args", [])
    assert cfg in server.get("args", [])


def test_generate_client_config_sse_claude_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE transport → claude-code gets url entry under mcpServers."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="sse", host="127.0.0.1", port=9000)
    result = json.loads(generate_client_config(args, "claude-code"))
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server["url"] == "http://127.0.0.1:9000/sse"
    assert "command" not in server


def test_generate_client_config_sse_includes_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE transport with api_key → headers block with X-API-Key."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="sse", api_key="tok123")
    result = json.loads(generate_client_config(args, "claude-desktop"))
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server.get("headers", {}).get("X-API-Key") == "tok123"


def test_generate_client_config_sse_https_with_ssl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE transport with ssl_certfile → https URL."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="sse", ssl_certfile="cert.pem", ssl_keyfile="key.pem")
    result = json.loads(generate_client_config(args, "claude-desktop"))
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server["url"].startswith("https://")


def test_generate_client_config_cursor_uses_mcp_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cursor client uses mcpServers root key and no type field (same shape as claude-desktop)."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="stdio")
    result = json.loads(generate_client_config(args, "cursor"))
    assert "mcpServers" in result
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server["command"] == "mcp-stdio-bridge"
    assert "type" not in server


def test_generate_client_config_vscode_has_type_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vscode client emits 'type' field and uses 'servers' root key."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="stdio")
    result = json.loads(generate_client_config(args, "vscode"))
    assert "servers" in result
    server = result["servers"]["mcp-stdio-bridge"]
    assert server["type"] == "stdio"


def test_generate_client_config_copilot_root_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """copilot client uses github.copilot.mcp.servers root key."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="sse")
    result = json.loads(generate_client_config(args, "copilot"))
    assert "github.copilot.mcp.servers" in result
    server = result["github.copilot.mcp.servers"]["mcp-stdio-bridge"]
    assert server["type"] == "sse"


def test_client_config_info_paths() -> None:
    """client_config_info returns path and note for every supported client."""
    from mcp_stdio_bridge.config import client_config_info

    for client in ("claude-desktop", "claude-code", "cursor", "gemini", "vscode", "copilot"):
        info = client_config_info(client)
        assert "path" in info and info["path"]
        assert "note" in info and info["note"]


def test_client_config_info_cursor_path() -> None:
    """cursor always resolves to ~/.cursor/mcp.json regardless of platform."""
    from mcp_stdio_bridge.config import client_config_info

    info = client_config_info("cursor")
    assert "cursor" in info["path"]
    assert "mcpServers" in info["note"]


def test_client_config_info_gemini_path() -> None:
    """gemini resolves to ~/.gemini/settings.json."""
    from mcp_stdio_bridge.config import client_config_info

    info = client_config_info("gemini")
    assert ".gemini" in info["path"]
    assert "mcpServers" in info["note"]


def test_generate_client_config_gemini_uses_mcp_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gemini client uses mcpServers root key with no type field."""
    import json
    from mcp_stdio_bridge.config import generate_client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _client_args(transport="stdio")
    result = json.loads(generate_client_config(args, "gemini"))
    assert "mcpServers" in result
    server = result["mcpServers"]["mcp-stdio-bridge"]
    assert server["command"] == "mcp-stdio-bridge"
    assert "type" not in server


def test_client_config_info_vscode_project_local() -> None:
    """vscode path is project-local (.vscode/mcp.json)."""
    from mcp_stdio_bridge.config import client_config_info

    info = client_config_info("vscode")
    assert ".vscode" in info["path"]


def test_client_config_info_darwin_paths() -> None:
    """On darwin, claude-desktop and copilot use Library/Application Support paths."""
    from mcp_stdio_bridge.config import client_config_info

    with patch("mcp_stdio_bridge.config.sys.platform", "darwin"):
        info = client_config_info("claude-desktop")
        assert "Library/Application Support" in info["path"]
        info = client_config_info("copilot")
        assert "Library/Application Support" in info["path"]


def test_client_config_info_linux_paths() -> None:
    """On linux, claude-desktop and copilot use ~/.config paths."""
    from mcp_stdio_bridge.config import client_config_info

    with patch("mcp_stdio_bridge.config.sys.platform", "linux"):
        info = client_config_info("claude-desktop")
        assert ".config/Claude" in info["path"]
        info = client_config_info("copilot")
        assert ".config/Code" in info["path"]


def test_finalize_settings_verbose_sets_debug_level() -> None:
    """--verbose flag causes finalize_settings to set logging_level to DEBUG."""
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo", "--verbose"]):
        finalize_settings(parse_args())
        assert settings["logging_level"] == "DEBUG"


def test_main_generate_client_config_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--generate-client-config prints JSON to stdout and info + warning to stderr."""
    import json
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    with patch(
        "sys.argv",
        ["mcp-stdio-bridge", "--generate-client-config", "claude-code", "--transport", "stdio"],
    ):
        with patch("anyio.run") as mock_run:
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 0
            mock_run.assert_not_called()
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "mcpServers" in result
    assert "Destination:" in captured.err
    assert "Warning:" in captured.err


def test_main_generate_client_config_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--output writes JSON to the given file instead of stdout."""
    import json
    from mcp_stdio_bridge.main import main as cli_main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    out_file = str(tmp_path / "client_config.json")
    with patch(
        "sys.argv",
        [
            "mcp-stdio-bridge",
            "--generate-client-config",
            "vscode",
            "--transport",
            "stdio",
            "--output",
            out_file,
        ],
    ):
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Warning:" in captured.err
    assert str(Path(out_file).resolve()) in captured.err
    result = json.loads(Path(out_file).read_text())
    assert "servers" in result


def test_config_global_cwd() -> None:
    """Test that the global --cwd flag is correctly parsed into settings."""
    test_cwd = "/home/user/test-cwd"
    with patch("sys.argv", ["mcp-stdio-bridge", "--command", "echo", "--cwd", test_cwd]):
        finalize_settings(parse_args())
        assert settings["cwd"] == test_cwd
