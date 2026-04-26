# MCP Stdio Bridge

A generic, professional-grade gateway that bridges Model Context Protocol (MCP) servers between **SSE (Server-Sent Events)** and **Stdio** transports.

## Features

- **Generic Bridge**: Works with any executable that speaks MCP over stdio.
- **Command Wrapper Mode**: Directly wrap any CLI utility (like `wp-cli`, `git`, or custom scripts) into a restricted MCP server without writing external scripts.
- **Dual Transport Support**: Run over **SSE (HTTP/HTTPS)** for remote access or **Stdio** for local use by MCP clients.
- **100% Test Coverage**: Exhaustive test suite ensuring stability across all transports, operational modes, and failure paths.
- **YAML Configuration**: Easily manage settings via a central config file.
- **Dynamic Configuration Reload**: Opt-in feature to live-reload settings from `config.yaml` without dropping active sessions.
- **Idle Session Timeouts**: Automatically terminates stalled proxy and wrapper sessions to prevent resource leaks.
- **Process Management**: Automatically spawns, manages, and cleans up subprocesses for bridging.

- **Security**:
  - API key authentication (Header or Query Param).
  - Restricted argument prefixing and regex filtering for wrapped commands.
  - Built-in **Directory Traversal Protection** for local tool execution.
  - **Environment Scrubbing**: Allowlist/Denylist variables passed to subprocesses.
  - **Secret Masking**: Sensitive keys are automatically hidden from logs.
  - Connection limiting and message size throttling.
  - SSL/TLS with client certificate and CRL support.
  - HSTS and secure security headers.

## Installation

Install the package using pip:

```bash
pip install mcp-stdio-bridge
```

## Documentation

For detailed information on configuring and deploying the bridge, see:
- [docs/configuration.md](docs/configuration.md): Full settings reference and JSON Schema.
- [docs/deployment.md](docs/deployment.md): Docker and local execution guides.
- [docs/mcp-servers.md](docs/mcp-servers.md): Integration requirements for MCP servers.
- [docs/roadmap.md](docs/roadmap.md): Future considerations and planned features.

### Architecture & Design

To understand the internal logic and security model, refer to:
- [docs/architecture.md](docs/architecture.md): Modular structure and transport/mode design.
- [docs/security.md](docs/security.md): Detailed security features and sandboxing.
- [docs/workflows.md](docs/workflows.md): Sequential operational flows.

### Examples

Check the [examples/](examples/) directory for templates covering common use cases:
- `wp-cli-wrapper.yaml`: Manage WordPress via MCP (Mix of Allowlist/Denylist).
- `git-wrapper.yaml`: Expose Git operations to local clients (Allowlist-only).
- `sqlite-proxy.yaml`: Bridge an existing SQLite MCP server to SSE.
- `security-patterns.yaml`: Advanced regex-based security filtering.
- `docker-tool-wrapper.yaml`: Using custom environment variables per tool.

Example `config.yaml`:

```yaml
host: "127.0.0.1"
port: 8000
command: "python your_mcp_server.py"
verbose: true
api_key: "your-secret-key"
max_connections: 5
cors_origins: ["*"]
# ssl_keyfile: "path/to/key.pem"
# ssl_certfile: "path/to/cert.pem"
```

## Running the Bridge

```bash
mcp-stdio-bridge
```

## Docker

You can run the bridge using Docker:

```bash
# Build the image
docker build -t mcp-stdio-bridge .

# Run with a mounted config file
docker run -p 8000:8000 -v $(pwd)/config.yaml:/app/config.yaml mcp-stdio-bridge
```

Alternatively, use Docker Compose:

```bash
docker-compose up -d
```

### Customization Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--host` | Host to bind the server to | `0.0.0.0` |
| `--port` | Port to bind the server to | `8000` |
| `--command` | The command to run for each session (Proxy Mode) | `None` |
| `--mode` | Operation mode (`proxy` or `command-wrapper`) | `proxy` |
| `--transport` | Transport protocol (`sse` or `stdio`) | `sse` |
| `--api-key` | Optional API key for authentication | `None` |
| `--max-connections` | Max concurrent subprocesses | `10` |
| `--max-message-size` | Max message size in bytes | `1048576` |
| `--ssl-keyfile` | Path to SSL key file | `None` |
| `--ssl-certfile` | Path to SSL cert file | `None` |
| `--ssl-keyfile-password` | Password for SSL key file | `None` |
| `--ssl-ca-certs` | Path to SSL CA certificates file | `None` |
| `--ssl-crlfile` | Path to SSL CRL file | `None` |
| `--ssl-client-cert-required`| Require client certificates | `False` |
| `--ssl-protocol` | SSL protocol (`TLSv1_2`, `TLSv1_3`) | `TLSv1_2` |
| `--ssl-ciphers` | SSL ciphers | `None` |
| `--hsts` | Enable HSTS | `False` |
| `--no-security-headers` | Disable default security headers | `False` |
| `--cors-origins` | CORS origins (space-separated) | `["*"]` |
| `--idle-timeout` | Idle timeout for proxy sessions (seconds) | `3600` |
| `--env-allowlist` | Allowlist of environment variables | `None` |
| `--env-denylist` | Denylist of environment variables | `[...]` |
| `--log-level` | Set the logging level (DEBUG, INFO, etc.) | `INFO` |
| `--logging-config` | Path to a custom logging config file | `None` |
| `--watch-config` | Enable dynamic config reloading | `False` |
| `--rate-limit-requests` | Max requests per client per window (0 = disabled) | `0` |
| `--rate-limit-window` | Rate limit window size in seconds | `60` |
| `--version` | Display the application version and exit | |
| `-v`, `--verbose` | Enable verbose logging | `False` |

> **Note**: When operating in Stdio transport mode, all non-JSON-RPC output (including warnings, errors, and informational logs) is directed to `sys.stderr` to maintain JSON-RPC stream integrity.

## Development

Install all dependencies (including test and dev extras):

```bash
pip install -e ".[dev,test]"
```

Run the full test suite (the `--timeout=10` flag is required — SSE transport tests can hang without it):

```bash
pytest --timeout=10
```

Lint, type-check, and security scan:

```bash
ruff check src tests
mypy src
bandit -r src -c pyproject.toml
```

## License

This is free and unencumbered software released into the public domain. For more information, please refer to the `LICENSE` file or <http://unlicense.org/>.
