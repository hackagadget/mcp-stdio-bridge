# SPDX-License-Identifier: Unlicense
"""
Configuration Module
====================
Handles settings, CLI arguments, and schema validation.
"""

import argparse
import json
import os
import sys
import secrets
import jsonschema
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover
    from importlib_resources import files as _resource_files  # type: ignore

DEFAULT_SETTINGS: Dict[str, Any] = {
    "host": "localhost",
    "port": 8000,
    "transport": "stdio",
    "mode": "proxy",
    "logging_level": "INFO",
    "logging_config": None,
    "watch_config": False,
    "api_key": None,
    "cors_origins": ["*"],
    "ssl_keyfile": None,
    "ssl_certfile": None,
    "ssl_ca_certs": None,
    "ssl_keyfile_password": None,
    "ssl_protocol": "TLSv1_2",
    "ssl_client_cert_required": False,
    "ssl_ciphers": None,
    "hsts": False,
    "security_headers": True,
    "max_connections": 1,
    "max_message_size": 1048576,
    "idle_timeout": 3600,
    "rate_limit_requests": 0,
    "rate_limit_window": 60,
    "cwd": None,
    "wrapped_commands": [],
    "groups": {},
    "env_allowlist": None,
    "env_denylist": [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "DB_PASSWORD",
        "DATABASE_URL",
        "SECRET_KEY",
        "API_KEY",
    ],
    "command": None,
    "pid_file": None,
    "daemonize": False,
    "verbose": False,
}

settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()
_last_args: Optional[argparse.Namespace] = None
_config_files: List[str] = []


def parse_args() -> argparse.Namespace:
    from . import __version__

    parser = argparse.ArgumentParser(description="MCP Stdio Bridge")
    parser.add_argument("--config", help="Path to YAML configuration file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", help="SSE host")
    parser.add_argument("--port", type=int, help="SSE port")
    parser.add_argument("--transport", choices=["stdio", "sse"], help="Transport protocol")
    parser.add_argument("--mode", choices=["proxy", "command-wrapper"], help="Operation mode")
    parser.add_argument("--command", help="Command for proxy mode")
    parser.add_argument("--logging-level", help="Logging level")
    parser.add_argument("--logging-config", help="Custom logging config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG logging")
    parser.add_argument("--api-key", help="API Key for SSE")
    parser.add_argument("--cors-origins", nargs="+", help="CORS allowed origins")
    parser.add_argument("--ssl-keyfile", help="Path to SSL key file")
    parser.add_argument("--ssl-certfile", help="Path to SSL certificate file")
    parser.add_argument("--ssl-ca-certs", help="Path to SSL CA certificates file")
    parser.add_argument("--ssl-keyfile-password", help="Password for SSL key file")
    parser.add_argument("--ssl-protocol", help="SSL protocol version")
    parser.add_argument(
        "--ssl-client-cert-required", action="store_true", help="Require client cert"
    )
    parser.add_argument("--hsts", action="store_true", help="Enable HSTS")
    parser.add_argument(
        "--no-security-headers",
        action="store_false",
        dest="security_headers",
        help="Disable security headers",
    )
    parser.set_defaults(security_headers=True)
    parser.add_argument("--max-connections", type=int, help="Max concurrent SSE connections")
    parser.add_argument("--max-message-size", type=int, help="Max message size in bytes")
    parser.add_argument("--idle-timeout", type=int, help="Idle timeout in seconds")
    parser.add_argument("--cwd", help="Global working directory for subprocesses")
    parser.add_argument("--max-retries", type=int, help="Max command retries in proxy mode")
    parser.add_argument("--retry-delay", type=float, help="Initial retry delay in seconds")
    parser.add_argument("--retry-max-delay", type=float, help="Maximum retry delay in seconds")
    parser.add_argument("--retry-multiplier", type=float, help="Retry delay multiplier")
    parser.add_argument(
        "--watch-config", action="store_true", help="Enable dynamic config reloading"
    )
    parser.add_argument("--env-allowlist", nargs="+", help="Allowlist of env vars")
    parser.add_argument("--env-denylist", nargs="+", help="Denylist of env vars")
    parser.add_argument("--generate-api-key", action="store_true", help="Generate random API key")
    parser.add_argument("--generate-config", action="store_true", help="Generate minimal config")
    parser.add_argument(
        "--generate-client-config",
        choices=["claude-desktop", "claude-code", "cursor", "gemini", "vscode", "copilot"],
        metavar="CLIENT",
        help=(
            "Generate MCP client config snippet for the specified client"
            " (choices: claude-desktop, claude-code, cursor, gemini, vscode, copilot)"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Write generated client config to FILE instead of stdout",
    )
    parser.add_argument("--pid-file", metavar="FILE", help="Write process PID to FILE on startup")
    parser.add_argument(
        "--daemonize", "-D", action="store_true",
        help="Detach from terminal and run as a daemon (POSIX only)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Send SIGHUP to a running bridge process identified by --pid-file (POSIX only)",
    )
    parser.add_argument(
        "--check-config", action="store_true", help="Validate configuration and exit"
    )
    parser.add_argument(
        "--warnings-as-errors", action="store_true", help="Treat warnings as errors"
    )
    return parser.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading config from {path}: {e}", file=sys.stderr)
        return {}


def get_env_overrides() -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    prefix = "MCP_"
    for key, val in os.environ.items():
        if key.startswith(prefix):
            s_key = key[len(prefix) :].lower()
            if s_key in DEFAULT_SETTINGS:
                default = DEFAULT_SETTINGS[s_key]
                if isinstance(default, bool):
                    overrides[s_key] = val.lower() in ("true", "1", "yes")
                elif isinstance(default, int):
                    overrides[s_key] = int(val)
                elif isinstance(default, list):
                    overrides[s_key] = [i.strip() for i in val.split(",")]
                else:
                    overrides[s_key] = val
    return overrides


def finalize_settings(args: argparse.Namespace) -> None:
    global _last_args
    _last_args = args
    _apply_settings(args)


def reload_settings() -> bool:
    if _last_args:
        _apply_settings(_last_args)
        return True
    return False


def get_config_files() -> List[str]:
    return _config_files


def _apply_settings(args: argparse.Namespace) -> None:
    global _config_files
    _config_files = []
    final = DEFAULT_SETTINGS.copy()

    # 1. Hierarchy (Always track files for tests)
    home = Path.home() / ".mcp-stdio-bridge.yaml"
    local = Path.cwd() / "config.yaml"
    for p in [str(home), str(local)]:
        _config_files.append(p)
        final.update(load_config(p))

    if args.config:
        _config_files.append(args.config)
        final.update(load_config(args.config))

    final.update(get_env_overrides())

    cli_dict = {k: v for k, v in vars(args).items() if v is not None and k != "config"}
    if args.verbose:
        cli_dict["logging_level"] = "DEBUG"

    # Merge CLI and hyphens
    for k, v in cli_dict.items():
        final[k] = v
        final[k.replace("_", "-")] = v

    # 5. Sanity Warnings (only if explicitly set on CLI)
    if final["transport"] == "stdio":
        sse_only_keys = [
            "host",
            "port",
            "cors_origins",
            "api_key",
            "ssl_keyfile",
            "ssl_certfile",
            "ssl_ca_certs",
            "hsts",
            "security_headers",
        ]
        for key in sse_only_keys:
            if key in cli_dict and cli_dict[key] != DEFAULT_SETTINGS[key]:
                print(
                    f"Warning: Option --{key.replace('_', '-')} is ignored"
                    " in Stdio transport mode.",
                    file=sys.stderr,
                )

    if (
        final.get("env_allowlist") is not None
        and final.get("env_denylist") != DEFAULT_SETTINGS["env_denylist"]
    ):
        print(
            "Warning: Both env_allowlist and env_denylist are set."
            " env_allowlist will take precedence.",
            file=sys.stderr,
        )

    settings.clear()
    settings.update(final)


def prepare_env() -> Dict[str, str]:
    env = os.environ.copy()
    allow = settings.get("env_allowlist")
    deny = settings.get("env_denylist", [])
    if allow is not None:
        return {k: env[k] for k in allow if k in env}
    for k in deny:
        if k in env:
            del env[k]
    return env


def _load_schema() -> Dict[str, Any]:
    text = _resource_files("mcp_stdio_bridge").joinpath("schema.json").read_text(encoding="utf-8")
    result: Dict[str, Any] = json.loads(text)
    return result


def validate_settings(final: Dict[str, Any]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if final.get("mode") == "proxy" and not final.get("command"):
        errors.append("proxy mode requires 'command' to be set")
    if final.get("mode") == "command-wrapper" and not final.get("wrapped_commands"):
        errors.append("command-wrapper mode requires at least one entry in 'wrapped_commands'")

    h_key, h_cert = bool(final.get("ssl_keyfile")), bool(final.get("ssl_certfile"))
    if h_key and not h_cert:
        errors.append("'ssl_keyfile' is set but 'ssl_certfile' is missing")
    if h_cert and not h_key:
        errors.append("'ssl_certfile' is set but 'ssl_keyfile' is missing")

    if final.get("transport") == "stdio":
        sse_only_keys = [
            "host",
            "port",
            "cors_origins",
            "api_key",
            "ssl_keyfile",
            "ssl_certfile",
            "ssl_ca_certs",
            "hsts",
            "security_headers",
        ]
        for key in sse_only_keys:
            if final.get(key) != DEFAULT_SETTINGS.get(key):
                warnings.append(f"'{key}' is set but ignored in stdio transport mode")

    if final.get("daemonize") and final.get("transport") == "stdio":
        errors.append("'daemonize' is incompatible with stdio transport")

    if (
        final.get("env_allowlist") is not None
        and final.get("env_denylist") != DEFAULT_SETTINGS["env_denylist"]
    ):
        warnings.append(
            "both 'env_allowlist' and 'env_denylist' are set; env_allowlist takes precedence"
        )
    return errors, warnings


_CLI_ONLY = {
    "config",
    "check_config",
    "warnings_as_errors",
    "generate_api_key",
    "generate_config",
    "generate_client_config",
    "output",
    "verbose",
    "version",
}


def generate_config(args: argparse.Namespace) -> str:
    config: Dict[str, Any] = {}
    for k, v in vars(args).items():
        if k in _CLI_ONLY or v is None or v == DEFAULT_SETTINGS.get(k):
            continue
        config[k] = v
    if args.generate_api_key:
        config["api_key"] = secrets.token_urlsafe(32)
    header = "# Generated by mcp-stdio-bridge --generate-config\n"
    return header + yaml.dump(config, default_flow_style=False, sort_keys=True)


def check_config(args: argparse.Namespace, warnings_as_errors: bool) -> int:
    prog, has_err = "mcp-stdio-bridge", False
    schema = _load_schema()
    file_schema = {k: v for k, v in schema.items() if k != "oneOf"}
    final = DEFAULT_SETTINGS.copy()
    sources: List[str] = []

    paths = [str(Path.home() / ".mcp-stdio-bridge.yaml"), str(Path.cwd() / "config.yaml")]
    if args.config:
        paths.append(args.config)

    for p in paths:
        if not os.path.exists(p):
            continue
        sources.append(p)
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            jsonschema.validate(raw, file_schema)
            final.update(raw)
        except Exception as e:
            msg = getattr(e, "message", str(e))
            print(f"{prog}: [error] {p}: {msg}", file=sys.stderr)
            has_err = True

    final.update(get_env_overrides())
    overrides = {k: v for k, v in vars(args).items() if v is not None and k not in _CLI_ONLY}
    final.update(overrides)

    errs, warns = validate_settings(final)
    for m in errs:
        print(f"{prog}: [error] {m}", file=sys.stderr)
        has_err = True
    for m in warns:
        lvl = "error" if warnings_as_errors else "warn"
        print(f"{prog}: [{lvl}] {m}", file=sys.stderr)
        if warnings_as_errors:
            has_err = True

    if has_err:
        print(f"{prog}: configuration has errors", file=sys.stderr)
        return 1
    print(
        f"{prog}: configuration ok ({', '.join(sources) if sources else 'defaults only'})",
        file=sys.stderr,
    )
    return 0


def _build_sse_entry(client: str, url: str, api_key: Optional[str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {}
    if client in ("vscode", "copilot"):
        entry["type"] = "sse"
    entry["url"] = url
    if api_key:
        entry["headers"] = {"X-API-Key": api_key}
    return entry


def _build_stdio_entry(client: str, cmd_args: List[str]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {}
    if client in ("vscode", "copilot"):
        entry["type"] = "stdio"
    entry["command"] = "mcp-stdio-bridge"
    if cmd_args:
        entry["args"] = cmd_args
    return entry


def _wrap_entry(client: str, server_name: str, entry: Dict[str, Any]) -> str:
    if client in ("claude-desktop", "claude-code", "cursor", "gemini"):
        config: Dict[str, Any] = {"mcpServers": {server_name: entry}}
    elif client == "vscode":
        config = {"servers": {server_name: entry}}
    else:  # copilot
        config = {"github.copilot.mcp.servers": {server_name: entry}}
    return json.dumps(config, indent=2) + "\n"


def client_config_info(client: str) -> Dict[str, str]:
    """Return destination path and merge note for the given MCP client."""
    plat = sys.platform
    if client == "claude-desktop":
        if plat == "darwin":
            path = "~/Library/Application Support/Claude/claude_desktop_config.json"
        elif plat == "win32":
            path = "%APPDATA%\\Claude\\claude_desktop_config.json"
        else:
            path = "~/.config/Claude/claude_desktop_config.json"
        note = "Merge the 'mcpServers' block into the existing file."
    elif client == "claude-code":
        path = "~/.claude/settings.json  (global)  or  .claude/settings.json  (project)"
        note = "Merge the 'mcpServers' block into the existing file."
    elif client == "cursor":
        path = "~/.cursor/mcp.json"
        note = "Merge the 'mcpServers' block into the existing file."
    elif client == "gemini":
        path = "~/.gemini/settings.json"
        note = "Merge the 'mcpServers' block into the existing file."
    elif client == "vscode":
        path = ".vscode/mcp.json  (project-local)"
        note = "Create the file or merge the 'servers' block into the existing file."
    else:  # copilot
        if plat == "darwin":
            path = "~/Library/Application Support/Code/User/settings.json"
        elif plat == "win32":
            path = "%APPDATA%\\Code\\User\\settings.json"
        else:
            path = "~/.config/Code/User/settings.json"
        note = "Merge the 'github.copilot.mcp.servers' block into VS Code user settings."
    return {"path": path, "note": note}


def generate_client_config(args: argparse.Namespace, client: str) -> str:
    """Return a JSON client config snippet for the requested MCP client."""
    final = DEFAULT_SETTINGS.copy()
    paths = [str(Path.home() / ".mcp-stdio-bridge.yaml"), str(Path.cwd() / "config.yaml")]
    if args.config:
        paths.append(args.config)
    for p in paths:
        final.update(load_config(p))
    final.update(get_env_overrides())
    overrides = {k: v for k, v in vars(args).items() if v is not None and k not in _CLI_ONLY}
    final.update(overrides)

    server_name = "mcp-stdio-bridge"
    transport = final.get("transport", "stdio")

    if transport == "sse":
        scheme = "https" if final.get("ssl_certfile") else "http"
        host = final.get("host", "localhost")
        port = final.get("port", 8000)
        url = f"{scheme}://{host}:{port}/sse"
        entry = _build_sse_entry(client, url, final.get("api_key"))
    else:
        cmd_args: List[str] = []
        if args.config:
            cmd_args.extend(["--config", args.config])
        entry = _build_stdio_entry(client, cmd_args)

    return _wrap_entry(client, server_name, entry)


def get_masked_settings() -> Dict[str, Any]:
    masked = settings.copy()
    sens = ["api_key", "ssl_keyfile_password", "aws_secret_access_key"]
    for k in masked:
        if k.lower() in sens and masked[k]:
            masked[k] = "********"
    return masked
