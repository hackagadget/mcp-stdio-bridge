# Integrating MCP Servers

The bridge supports two distinct ways to expose tools via MCP: **Proxy Mode** and **Command Wrapper Mode**.

## 1. Proxy Mode

In this mode, the bridge forwards JSON-RPC messages between an SSE client and an external process that is itself a fully-compliant MCP server.

### Server Requirements

For an external server to function correctly in `proxy` mode, it must adhere to the following rules:

### 1. Standard I/O Hygiene (Crucial)
The bridge expects **only** valid JSON-RPC messages on `stdout`.
-   **Do not** use `print()` or `console.log()` for debugging if they write to `stdout`.
-   All logging, warnings, and informational messages **must** be written to `stderr`.
-   If your server prints "Server started..." to `stdout`, the bridge will fail to parse it as JSON and log an error.

### 2. Signal Handling
When an SSE client disconnects, the bridge sends a `SIGTERM` (or `terminate()` call) to the subprocess.
-   Your server should handle termination signals gracefully to clean up resources.

### 3. Non-Interactive
The bridge cannot provide input to interactive prompts. Ensure your server runs without intervention.

## 2. Command Wrapper Mode

In this mode, the bridge **hosts its own internal MCP server**. You don't need to write any MCP-compliant code. Instead, you provide a list of standard CLI tools (like `ls`, `grep`, `git`, `wp-cli`) and the bridge exposes them as native MCP tools.

### Benefits
- **Ease of Use**: No need for external scripts or MCP SDKs in your tools.
- **Security**: You can restrict which subcommands are allowed using `forbidden_args` or `forbidden_patterns`.
- **Output Handling**: The bridge automatically captures `stdout` and `stderr` and formats them into an MCP `TextContent` response.

### Custom Environment Variables
You can provide tool-specific environment variables that are merged with the sanitized system environment:
```yaml
wrapped_commands:
  - name: "my_tool"
    command: "bin/tool"
    env:
      TOOL_CONFIG_PATH: "/etc/tool/config.json"
```

### Example Configuration
```yaml
mode: "command-wrapper"
wrapped_commands:
  - name: "disk_usage"
    description: "Check available disk space"
    command: "df -h"
```

## Configuration Tips

### Command Paths
In your `config.yaml`, the `command` is parsed using `shlex`.
-   **Local Scripts**: If using a script, ensure the interpreter is in the path or use the full path:
    ```yaml
    command: "python /opt/mcp/my_server.py"
    ```
-   **Executable Bit**: On Linux/macOS, ensure your script is executable if you are calling it directly (e.g., `command: "./my_server.sh"`).

### Environment Variables
Subprocesses inherit the environment variables of the bridge process. You can control this behavior for security using **Environment Hygiene** (see below) or manually:
1.  Set them in the shell before starting the bridge.
2.  Set them in a systemd unit file or Docker Compose.
3.  Use the `env_allowlist` setting (recommended).

### Remote Servers (SSH)
You can bridge to an MCP server running on a different machine via SSH:
```yaml
command: "ssh user@remote-host mcp-server-command"
```
*Note: Ensure the bridge user has SSH keys configured for the remote host, as interactive password prompts are not supported.*

## 3. Environment Hygiene (Advanced)

By default, the bridge removes sensitive internal variables (like `MCP_API_KEY` and `SSL_KEYFILE_PASSWORD`) before spawning a subprocess. You can further restrict the environment using:

- **`env_allowlist`**: If provided, child processes will ONLY inherit these variables.
- **`env_denylist`**: Specific variables to remove from the child process's environment.

```yaml
# Only pass DB_URL and PATH to the MCP server
env_allowlist:
  - "DB_URL"
  - "PATH"
```

## Troubleshooting

If the bridge connects but messages aren't flowing:
1.  **Check Bridge Logs**: Run with `--verbose` to see exactly what is being sent and received.
2.  **Verify the Command**: Try running the exact `command` from your terminal. Does it start without error? Does it respond to JSON-RPC on stdin?
3.  **Check Stderr**: The bridge forwards the subprocess's `stderr` to its own logs. Look there for Python tracebacks or Node.js errors from your server.
