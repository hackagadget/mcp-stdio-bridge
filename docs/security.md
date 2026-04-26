# Security Model

The **MCP Stdio Bridge** prioritizes security by implementing multiple layers of defense-in-depth. It is designed to safely expose local tools and servers to potentially untrusted environments.

## Transport Security

### API Key Authentication
For the SSE transport, the bridge supports mandatory API key validation. The key can be provided via the `X-API-Key` header or an `api_key` query parameter.

### SSL/TLS and HTTPS
The bridge supports built-in SSL/TLS termination with the following hardening features:
-   **Minimum TLS version**: Defaults to TLS 1.2, configurable to TLS 1.3.
-   **Client Certificate Validation**: Optional requirement for clients to provide a valid certificate (Mutual TLS).
-   **CRL Support**: Support for Certificate Revocation Lists to block compromised client certificates.

### Secure Headers
-   **HSTS**: Optional HTTP Strict Transport Security.
-   **Security Middleware**: Adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a restrictive `Content-Security-Policy`.

### Rate Limiting
To protect against DoS attacks and resource exhaustion, the bridge implements global per-IP rate limiting:
-   **Mechanism**: Uses a sliding-window algorithm to track request frequency.
-   **Configuration**: Configurable via `rate_limit_requests` and `rate_limit_window`.
-   **Trust Proxies**: Correctly identifies client IPs behind reverse proxies by respecting the `X-Forwarded-For` header.

## Execution Security (Command-Wrapper)

### Secure Jailing
When wrapping CLI tools, the bridge implements a "Security Jail":
-   **Allowlists (Opt-in)**: Strictly permit only specific subcommand prefixes or regex patterns.
-   **Denylists (Opt-out)**: Explicitly block dangerous subcommand prefixes (e.g., `rm`, `db query`).
-   **`forbidden_patterns` (Final Veto)**: Regex patterns in `forbidden_patterns` are always evaluated last, after allowlist and denylist checks. This makes them composable with either security model and is the recommended way to universally block dangerous flags such as `--exec` or `--require` that could execute arbitrary code regardless of the permitted subcommand.
-   **Config Groups (`groups` + `apply`)**: Named security presets defined once at the top level and referenced by individual commands. Group-defined `forbidden_patterns` are unioned with per-command patterns, ensuring a consistent security baseline across all tools without duplication.
-   **Shell-Injection Protection**: Subcommands are parsed using `shlex` and passed as a list to `anyio.run_process`, completely bypassing the shell.

### Path Sanitization
If a `cwd` (Working Directory) is set for a wrapped command:
-   **Directory Traversal**: The bridge blocks any argument containing `..`.
-   **Absolute Paths**: Unauthorized absolute paths (outside the `cwd`) are strictly prohibited.

### Resource Protection
-   **Execution Timeouts**: Every wrapped command has a configurable timeout (default 30s) to prevent runaway processes.
-   **Connection Limiting**: A global `CapacityLimiter` ensures that the system is not overwhelmed by too many concurrent sessions.

### Tool-Specific Isolation
In `command-wrapper` mode, each tool can define its own `env` dictionary. These variables are merged with the sanitized global environment, allowing you to provide specific credentials or paths to a single tool without exposing them to others.

## System Security

### Environment Hygiene
The bridge implements environment scrubbing to prevent sensitive data from leaking into child processes:
-   **`env_denylist`**: Automatically removes internal variables like `MCP_API_KEY`, `SSL_KEYFILE_PASSWORD`, and common cloud credentials.
-   **`env_allowlist`**: Provides a restrictive mode where child processes only inherit specifically permitted variables.

### Secret Masking
Application logs are automatically sanitized:
-   Sensitive configuration values (API keys, SSL passwords) are masked with `********` even in `DEBUG` or `verbose` logging modes.
-   JSON-RPC traffic logging (when `verbose` is enabled) is restricted to the relevant transport/mode logic.

### Session Lifecycle
-   **Idle Timeouts**: Proxy sessions are monitored. If no JSON-RPC traffic is detected for a configurable period (default 1 hour), the subprocess is terminated and the session is closed.
-   **Explicit Cleanup**: Subprocesses are aggressively terminated using `terminate()` in `finally` blocks to ensure no "ghost" processes remain.
