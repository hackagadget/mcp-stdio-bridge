# Operational Workflows

This document describes the sequential logical flows for the primary bridging operations of the **MCP Stdio Bridge**.

## 1. SSE Proxy Connection Flow

This workflow applies when `transport: "sse"` and `mode: "proxy"`.

1.  **Client Request**: An MCP client (e.g., an LLM integration) sends an HTTP GET request to the `/sse` endpoint.
2.  **Authentication**: The `APIKeyMiddleware` validates the request credentials.
3.  **Connection Limit Check**: The `CapacityLimiter` semaphore is checked. If full, a 503 Service Unavailable is returned.
4.  **Subprocess Spawn**:
    *   The `command` setting is parsed.
    *   Environment variables are sanitized using `env_denylist` and `env_allowlist`.
    *   The subprocess is spawned with piped `stdin`, `stdout`, and `stderr`.
5.  **Bridging Start**:
    *   The SSE event stream is established.
    *   Two concurrent tasks (`sse_to_proc` and `proc_to_sse`) begin forwarding messages.
6.  **Idle Monitoring**: An AnyIO Task Group monitors the session for inactivity based on `idle_timeout`.
7.  **Termination**:
    *   On client disconnect or timeout, the task group is cancelled.
    *   The subprocess is explicitly terminated via `terminate()`.
    *   The connection slot is released back to the semaphore.

## 2. Stdio Command-Wrapper Flow

This workflow applies when `transport: "stdio"` and `mode: "command-wrapper"`.

1.  **Bridge Start**: The bridge is executed (e.g., by Claude Desktop) and listens on its own `stdin`.
2.  **Tool Discovery**:
    *   The bridge initializes an internal MCP server.
    *   Registered `wrapped_commands` are exposed as native MCP tools.
3.  **Call Tool Request**: The client sends a `call_tool` JSON-RPC message over `stdin`.
4.  **Security Filtering**:
    *   The `subcommand` arguments are parsed using `shlex`.
    *   **Path Sanitization**: Checks for `..` and unauthorized absolute paths.
    *   **Safety Filter**: Validates against prefixes/patterns in `allowed_args` or `forbidden_args`.
5.  **Execution**:
    *   If permitted, the tool is spawned using `anyio.run_process` with the configured `timeout`.
    *   `stderr` is merged into `stdout` for the response.
6.  **Response**: The captured output is returned to the client as an MCP `TextContent` object via the bridge's `stdout`.

## Error Handling Strategy

The bridge employs a "Fail Fast and Securely" strategy:

-   **Bridging Errors**: If any stream in a proxy session fails, the entire session is immediately torn down and the subprocess killed.
-   **Security Failures**: Any security violation (blocked regex, traversal attempt) returns a descriptive error message to the MCP client rather than crashing the bridge.
-   **Execution Errors**: Non-zero exit codes from wrapped commands are treated as normal output, while system-level failures (e.g., executable not found) return a standardized error response.
