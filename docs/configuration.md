# Configuration File Format

The bridge can be configured using a YAML file. It searches for configuration in the following order:

1.  Explicit path provided via `--config` CLI argument.
2.  `config.yaml` in the current working directory.
3.  `~/.mcp-stdio-bridge.yaml` in the user's home directory.

## JSON Schema

A JSON Schema is available in the root of the repository as `schema.json`. You can use this for validation and autocompletion in many IDEs.

## Dynamic Configuration Reload

The bridge supports live reloading of `config.yaml` files without disconnecting active sessions. This feature is opt-in and must be enabled via the `watch_config` setting or `--watch-config` flag.
- **Mechanism**: The bridge polls `config.yaml` and `~/.mcp-stdio-bridge.yaml` for changes every 5 seconds.
- **Affected Settings**:
  - `wrapped_commands`: New tools will be available, and existing tools will be updated on the next `listTools` or `callTool` request.
  - `logging_level`: Log verbosity will change immediately.
  - `idle_timeout`, `max_message_size`: Values will be updated for *new* sessions.
- **Unaffected Settings**: Core transport settings like `host`, `port`, `mode`, and `transport` require a server restart to change.

### VS Code

Add this to your `settings.json`:

```json
"yaml.schemas": {
    "./schema.json": ["config.yaml", ".mcp-stdio-bridge.yaml"]
}
```

## Operation Modes

The bridge can operate in two modes:

### 1. Proxy Mode (`mode: "proxy"`)
The default mode. It spawns a new instance of a single MCP stdio server for every SSE connection and forwards all traffic between them. Requires the `command` setting.

### 2. Command Wrapper Mode (`mode: "command-wrapper"`)
Directly exposes one or more standard CLI tools as MCP tools. The bridge hosts an internal MCP server and executes the tools on demand. Requires the `wrapped_commands` setting.

## Settings

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `mode` | `string` | `"proxy"` | Operation mode: `"proxy"` or `"command-wrapper"`. |
| `transport` | `string` | `"sse"` | Transport protocol: `"sse"` (HTTP) or `"stdio"` (Standard I/O). |
| `host` | `string` | `"0.0.0.0"` | The hostname or IP address to bind the server to (SSE only). |
| `port` | `integer` | `8000` | The port to bind the server to (SSE only). |
| `command` | `string` | `null` | **(Proxy Mode Only)** The command to execute for each MCP session. |
| `wrapped_commands` | `list` | `[]` | **(Wrapper Mode Only)** List of CLI tools to wrap (see below). |
| `verbose` | `boolean` | `false` | If `true`, all JSON-RPC messages will be logged. |
| `api_key` | `string` | `null` | Optional API key for authentication (SSE only). |
| `max_connections` | `integer` | `10` | The maximum number of concurrent MCP sessions allowed. |
| `max_message_size` | `integer` | `1048576` | The maximum size of a single JSON-RPC message in bytes (1MB). |
| `logging_level` | `string` | `"INFO"` | Application logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `logging_config` | `string` | `null` | Path to a Python logging configuration file (YAML, JSON, or INI). |
| `watch_config` | `boolean` | `false` | If `true`, enables the background config file watcher for dynamic reloading. |
| `cors_origins` | `list` | `["*"]` | A list of allowed origins for CORS (SSE only). |
| `ssl_keyfile` | `string` | `null` | Path to the SSL key file for HTTPS. |
| `ssl_certfile` | `string` | `null` | Path to the SSL certificate file for HTTPS. |
| `ssl_keyfile_password` | `string` | `null` | Password for the SSL key file. |
| `ssl_ca_certs` | `string` | `null` | Path to CA certificates for client cert verification. |
| `ssl_crlfile` | `string` | `null` | Path to Certificate Revocation List (CRL) file. |
| `ssl_client_cert_required` | `boolean` | `false` | If `true`, requires a valid client certificate. |
| `ssl_protocol` | `string` | `"TLSv1_2"` | Minimum TLS protocol version (`TLSv1_2` or `TLSv1_3`). |
| `ssl_ciphers` | `string` | `null` | List of SSL ciphers to use. |
| `hsts` | `boolean` | `false` | If `true`, enables HTTP Strict Transport Security (HSTS). |
| `security_headers` | `boolean` | `true` | If `true`, adds standard security headers. |
| `idle_timeout` | `integer` | `3600` | Session timeout in seconds for idle connections. Set to 0 to disable. |
| `env_allowlist` | `list` | `null` | If set, only these environment variables are passed to subprocesses. |
| `env_denylist` | `list` | `[...]` | List of environment variables to explicitly remove from subprocesses (e.g., `MCP_API_KEY`). |

### Wrapped Command Schema

Each entry in `wrapped_commands` is an object:

| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | `string` | **(Required)** The tool name (e.g. `"wp_cli"`). |
| `description` | `string` | **(Required)** Description for the LLM. |
| `command` | `string` | **(Required)** The base executable (e.g. `"/usr/local/bin/wp"`). |
| `forbidden_args` | `list` | List of blocked argument prefixes for security (denylist). |
| `forbidden_patterns` | `list` | List of blocked regex patterns for security (denylist). |
| `allowed_args` | `list` | List of exclusively permitted argument prefixes (allowlist). |
| `allowed_patterns` | `list` | List of exclusively permitted regex patterns (allowlist). |
| `cwd` | `string` | Working directory for execution. If set, **automatic directory traversal protection** is enabled. |
| `env` | `object` | Dictionary of environment variables to set specifically for this tool. |
| `timeout` | `integer` | Execution timeout in seconds (default: 30). |

**Note**: You can use either an Allowlist (`allowed_args`, `allowed_patterns`) or a Denylist (`forbidden_args`, `forbidden_patterns`), but not both for the same command.

## Example `config.yaml`

```yaml
mode: "proxy"
transport: "sse"
command: "npx @modelcontextprotocol/server-sqlite --db /path/to/my.db"
api_key: "my-secret-token"
verbose: true
```

## Logging

### Log Levels
You can set the verbosity of the application using `logging_level`. Supported values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`.
-   `INFO` (Default): Logs connections, disconnections, and subprocess starts.
-   `DEBUG`: Logs full JSON-RPC traffic (if `verbose: true` is also set).

### Custom Logging Configuration
For advanced users, the `logging_config` setting allows you to point to a standard Python logging configuration file (`.yaml`, `.json`, or `.ini`).

## Environment Variables

Settings can be overridden by environment variables with the `MCP_` prefix:
- `MCP_HOST`
- `MCP_PORT`
- `MCP_API_KEY`
- `MCP_COMMAND`
- `MCP_MODE`
- `MCP_TRANSPORT`
- etc.
