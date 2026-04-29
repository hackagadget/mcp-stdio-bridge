# Deployment Guide

This document provides instructions and best practices for deploying the MCP Stdio Bridge in production environments.

## Deployment Options

### 1. Docker (Recommended)

The easiest way to deploy is using the provided Docker image.

**Production Considerations:**
-   **Config Security**: Mount your `config.yaml` as read-only.
-   **Resource Limits**: Use Docker resource limits to prevent a single MCP session from consuming too much CPU/Memory.
-   **Logging**: Map your log files to a persistent volume or use a `logging_config` to stream logs to a centralized collector (like Fluentd or ELK stack).

```bash
docker run -d \
  --name mcp-bridge \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /path/to/prod-config.yaml:/app/config.yaml:ro \
  mcp-stdio-bridge
```

### 2. Systemd (Bare Metal / VM)

If you are running on a Linux VM without Docker, use a systemd service to ensure the bridge starts on boot and restarts on failure.

**Example `/etc/systemd/system/mcp-bridge.service`:**

```ini
[Unit]
Description=MCP Stdio Bridge
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/mcp-bridge
ExecStart=/opt/mcp-bridge/.venv/bin/mcp-stdio-bridge --config /etc/mcp-bridge/config.yaml
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3. Local Execution (Stdio Transport)

The bridge can also be used as a local utility to wrap non-MCP CLI tools or local servers for use by desktop MCP clients (like Claude Desktop or Cursor).

**Example: Use the bridge to expose `git` to Claude Desktop**

1. Create a `git-config.yaml`:
   ```yaml
   transport: "stdio"
   mode: "command-wrapper"
   wrapped_commands:
     - name: "git_status"
       description: "Check git repository status"
       command: "git status"
   ```

2. Add this to your Claude Desktop configuration:
   ```json
   {
     "mcpServers": {
       "git-bridge": {
         "command": "mcp-stdio-bridge",
         "args": ["--config", "C:/path/to/git-config.yaml"]
       }
     }
   }
   ```

## Reverse Proxy (Nginx)

When deploying behind Nginx, you must ensure that SSE (Server-Sent Events) connections are not buffered and that headers are passed correctly.

**Example Nginx Configuration:**

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # Crucial for SSE
        proxy_set_header Connection '';
        proxy_set_header Cache-Control 'no-cache';
        proxy_buffering off;
        proxy_read_timeout 24h; # Keep long-lived sessions open

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Standalone Integration Tests

The `standalone_tests/` directory contains an integration test suite that exercises
the bridge end-to-end — real subprocesses, real transport, real WP-CLI mock — outside
of the unit-test harness.

### Running the tests

**Linux / macOS:**

```bash
./standalone_tests/run_tests.sh [-t <scenario>] [options]
```

**Windows (PowerShell):**

```powershell
.\standalone_tests\run_tests.ps1 [-t <scenario>] [options]
```

Run with `-h` for a full option listing, or `-t <scenario> -h` for help on a specific
scenario.

### Scenarios

| Scenario | Requires Docker | Description |
| :--- | :---: | :--- |
| `local-mock` | No | Runs the stdio command-wrapper against `mock_wp.py` (a WP-CLI stub) entirely in-process. The default scenario — no external services needed. |
| `start-bridge-sse` | No | Generates a config file and starts a local SSE bridge on port 8000. Run in one terminal, then run `test-sse` in another. |
| `test-sse` | No | Sends MCP requests to a running local bridge. Options: `-u <url>` (default `http://localhost:8000`), `-k <api-key>`. |
| `ssh` | No | Connects to a real remote host via SSH and runs the bridge over stdio. Options: `-H <user@host>`, `-c <remote-config-path>`, `-s <extra-ssh-args>`. |
| `docker-local` | Yes | Runs the `local-mock` scenario inside a Docker container. |
| `docker-sse` | Yes | Brings up a bridge service and a client container; verifies the full SSE pipeline. |
| `docker-ssh-direct` | Yes | Starts an SSH server container and runs a direct SSH stdio test against it. |
| `docker-ssh-proxy` | Yes | Starts an SSH server, a bridge that connects via SSH, and a client; tests the SSE-over-SSH-proxy topology. |

### Quick start (local, no Docker)

```bash
# 1. Run the local mock test (default scenario)
./standalone_tests/run_tests.sh

# 2. Two-terminal SSE smoke test
#    Terminal 1:
./standalone_tests/run_tests.sh -t start-bridge-sse
#    Terminal 2:
./standalone_tests/run_tests.sh -t test-sse
#    With auth:
./standalone_tests/run_tests.sh -t test-sse -u http://localhost:8000 -k mysecretkey

# 3. Real remote host over SSH
./standalone_tests/run_tests.sh -t ssh -H user@my-server -c /etc/mcp/config.yaml
```

### Docker scenarios

All Docker scenarios require Docker with Compose v2 (`docker compose`). They bring
up and tear down containers automatically, including cleanup on exit:

```bash
./standalone_tests/run_tests.sh -t docker-local
./standalone_tests/run_tests.sh -t docker-sse
./standalone_tests/run_tests.sh -t docker-ssh-direct
./standalone_tests/run_tests.sh -t docker-ssh-proxy
```

The `docker-ssh-proxy` scenario performs a full no-cache rebuild to ensure a clean
image; this is intentional and will take longer than the other Docker scenarios.

---

## Security Checklist

1.  **API Key**: Always use an `api_key` in production.
2.  **SSL/TLS**: Terminate SSL at your reverse proxy or configure the bridge's internal SSL settings.
3.  **Firewall**: Only expose the bridge to trusted IPs or your reverse proxy.
4.  **Connection Limits**: Set `max_connections` to a value appropriate for your server's RAM/CPU.
5.  **Message Limits**: Use `max_message_size` to prevent large-payload DoS attacks.
6.  **Unprivileged User**: Never run the bridge or the container as `root`.
