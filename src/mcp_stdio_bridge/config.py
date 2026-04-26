# SPDX-License-Identifier: Unlicense
"""
Configuration Management
========================

Handles loading, merging, and validating application settings from
CLI arguments, YAML files, and environment variables. Implements
a strict hierarchy where CLI > config.yaml > ~/.mcp-stdio-bridge.yaml.
"""
import os
import yaml
import argparse
from typing import Any, Dict
from pathlib import Path

# Application defaults
DEFAULT_SETTINGS: Dict[str, Any] = {
    "mode": "proxy",
    "transport": "sse",
    "host": "0.0.0.0",
    "port": 8000,
    "command": None,
    "wrapped_commands": [],
    "groups": {},
    "api_key": None,
    "max_connections": 10,
    "max_message_size": 1024 * 1024, # 1MB
    "verbose": False,
    "cors_origins": ["*"],
    "ssl_keyfile": None,
    "ssl_certfile": None,
    "ssl_keyfile_password": None,
    "ssl_ca_certs": None,
    "ssl_crlfile": None,
    "ssl_client_cert_required": False,
    "ssl_protocol": "TLSv1_2",
    "ssl_ciphers": None,
    "hsts": False,
    "security_headers": True,
    "logging_level": "INFO",
    "logging_config": None,
    "watch_config": False, # Watch for config file changes and reload
    "idle_timeout": 3600, # 1 hour default for proxy sessions
    "rate_limit_requests": 0,  # 0 = disabled; requests allowed per window
    "rate_limit_window": 60,   # window size in seconds
    "env_allowlist": None, # None means allow all (legacy) but usually restricted
    "env_denylist": [
        "MCP_API_KEY", "SSL_KEYFILE_PASSWORD", "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY"
    ]
}

# Global runtime settings object
settings = DEFAULT_SETTINGS.copy()

def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from a YAML file."""
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading config from {config_path}: {e}")
        return {}

def get_env_overrides() -> Dict[str, Any]:
    """Fetch overrides from environment variables (MCP_ prefix)."""
    overrides: Dict[str, Any] = {}
    for key in DEFAULT_SETTINGS:
        env_key = f"MCP_{key.upper()}"
        if env_key in os.environ:
            val = os.environ[env_key]
            # Simple type conversion
            if isinstance(DEFAULT_SETTINGS[key], bool):
                overrides[key] = val.lower() in ("true", "1", "yes")
            elif isinstance(DEFAULT_SETTINGS[key], int):
                overrides[key] = int(val)
            elif isinstance(DEFAULT_SETTINGS[key], list):
                overrides[key] = [item.strip() for item in val.split(",")]
            else:
                overrides[key] = val
    return overrides

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MCP Stdio Bridge - Gateway between SSE/Stdio transports.",
        exit_on_error=False # Prevent sys.exit in tests
    )
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--mode", choices=["proxy", "command-wrapper"], help="Operation mode")
    parser.add_argument("--transport", choices=["sse", "stdio"], help="Transport protocol")
    parser.add_argument("--host", help="Host to bind")
    parser.add_argument("--port", type=int, help="Port to bind")
    parser.add_argument("--command", help="Command for proxy mode")
    parser.add_argument("--api-key", help="API key for auth")
    parser.add_argument("--max-connections", type=int, help="Max concurrent sessions")
    parser.add_argument("--max-message-size", type=int, help="Max message size in bytes")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--log-level", dest="logging_level", help="Logging level")
    parser.add_argument("--logging-config", help="Path to logging config")

    # SSL/TLS Flags
    parser.add_argument("--ssl-keyfile", help="SSL key file")
    parser.add_argument("--ssl-certfile", help="SSL certificate file")
    parser.add_argument("--ssl-keyfile-password", help="Password for SSL key file")
    parser.add_argument("--ssl-ca-certs", help="SSL CA certificates file")
    parser.add_argument("--ssl-crlfile", help="SSL CRL file")
    parser.add_argument("--ssl-client-cert-required", action="store_true",
                        help="Require client certificates")
    parser.add_argument("--ssl-protocol", choices=["TLSv1_2", "TLSv1_3"],
                        help="SSL protocol")
    parser.add_argument("--ssl-ciphers", help="SSL ciphers")

    # Security Flags
    parser.add_argument("--hsts", action="store_true", help="Enable HSTS")
    parser.add_argument("--no-security-headers", dest="security_headers",
                        action="store_false", help="Disable default security headers")
    parser.add_argument("--cors-origins", nargs="+", help="CORS origins")
    parser.add_argument("--idle-timeout", type=int,
                        help="Idle timeout for proxy sessions (seconds)")
    parser.add_argument("--rate-limit-requests", type=int,
                        help="Max requests per client per window (0 = disabled)")
    parser.add_argument("--rate-limit-window", type=int,
                        help="Rate limit window size in seconds (default: 60)")

    # Environment Flags
    parser.add_argument("--env-allowlist", nargs="+", help="Allowlist of environment variables")
    parser.add_argument("--env-denylist", nargs="+", help="Denylist of environment variables")
    
    # Reloading
    parser.add_argument("--watch-config", action="store_true",
                        help="Enable dynamic config reloading")

    return parser.parse_args()

_last_args = None
_config_files: list[str] = []

def finalize_settings(args: argparse.Namespace) -> None:
    """
    Initial configuration setup. Stores args for future reloads.
    """
    global _last_args
    _last_args = args
    _apply_settings(args)

def reload_settings() -> bool:
    """
    Reloads configuration from disk and environment, re-applying CLI overrides.
    """
    if _last_args:
        _apply_settings(_last_args)
        return True
    return False

def get_config_files() -> list[str]:
    """Returns the list of potential config files to watch."""
    return _config_files

def _apply_settings(args: argparse.Namespace) -> None:
    """
    Internal logic to merge and apply settings from all sources.
    """
    global settings, _config_files
    _config_files = []

    # 1. Start with defaults
    final = DEFAULT_SETTINGS.copy()

    # 2. Check Home Directory
    home_config = Path.home() / ".mcp-stdio-bridge.yaml"
    _config_files.append(str(home_config))
    final.update(load_config(str(home_config)))

    # 3. Check Current Directory
    local_config = Path.cwd() / "config.yaml"
    _config_files.append(str(local_config))
    final.update(load_config(str(local_config)))

    # 4. Check Explicit Config
    if args.config:
        _config_files.append(args.config)
        final.update(load_config(args.config))
    # 5. Environment Overrides
    final.update(get_env_overrides())

    # 6. CLI Overrides
    cli_dict = {k: v for k, v in vars(args).items() if v is not None and k != "config"}
    final.update(cli_dict)

    # 7. Validation & Sanity Checks
    if final["transport"] == "stdio":
        sse_only_keys = [
            "host", "port", "cors_origins", "api_key", "ssl_keyfile",
            "ssl_certfile", "ssl_ca_certs", "hsts", "security_headers"
        ]
        for key in sse_only_keys:
            if key in cli_dict:
                print(f"Warning: Option --{key.replace('_', '-')} is ignored in Stdio "
                      f"transport mode.")

    if final["mode"] == "proxy" and not final["command"]:
        pass
    elif final["mode"] == "command-wrapper" and not final["wrapped_commands"]:
        pass

    if (
        final["env_allowlist"] is not None and
        final["env_denylist"] != DEFAULT_SETTINGS["env_denylist"]
    ):
        print("Warning: Both env_allowlist and env_denylist are set. env_allowlist will "
              "take precedence.")

    settings.clear()
    settings.update(final)

def get_masked_settings() -> Dict[str, Any]:
    """Return settings with sensitive values masked for logging."""
    masked = settings.copy()
    sensitive_keys = ["api_key", "ssl_keyfile_password", "aws_secret_access_key"]
    for key in masked:
        if key.lower() in sensitive_keys and masked[key]:
            masked[key] = "********"
    return masked

def prepare_env() -> Dict[str, str]:
    """
    Prepare a sanitized environment for subprocesses.
    Implements allowlist/denylist filtering for security.
    """
    env: Dict[str, str] = os.environ.copy()
    allowlist = settings.get("env_allowlist")
    denylist = settings.get("env_denylist", [])

    if allowlist is not None:
        # Allowlist approach: only allow specific variables
        return {k: env[k] for k in allowlist if k in env}

    # Denylist approach (default): remove known sensitive variables
    for key in denylist:
        if key in env:
            del env[key]

    return env
