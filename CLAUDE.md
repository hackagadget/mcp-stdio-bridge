# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with all extras
pip install -e ".[dev,test]"

# Lint / type-check / security scan
ruff check src tests
mypy src
bandit -r src -c pyproject.toml

# Run tests (coverage on by default; --timeout kills hanging tests)
pytest --timeout=10
pytest tests/test_config.py --timeout=10                                   # single file
pytest tests/test_config.py::test_config_schema_validation --timeout=10   # single test
pytest -vv --timeout=10                                                    # verbose
```

## Architecture

The bridge has two independent axes — **transport** and **mode** — that combine orthogonally:

- **Transport** controls how the MCP client connects: `sse` (HTTP + Server-Sent Events via Starlette/Uvicorn) or `stdio` (raw stdin/stdout).
- **Mode** controls what happens on the backend: `proxy` (transparently forwards to an external MCP subprocess) or `command-wrapper` (hosts an internal MCP server that executes CLI tools).

```
MCP Client
├── transport/
│   ├── sse.py    ─ Starlette + Uvicorn, API key auth, connection limits, SSL/TLS
│   └── stdio.py  ─ raw stdin/stdout (logging forced to stderr to avoid corruption)
└── mode/
    ├── proxy.py    ─ spawns one subprocess per connection, bridges streams bidirectionally
    │                 ActivityMonitor handles idle-timeout auto-termination
    └── wrapper.py  ─ internal MCP server; each wrapped_commands entry becomes an MCP tool
                      argument allowlist/denylist + shlex parsing (no shell=True)
                      top-level `groups` define reusable presets applied via `apply:` in each command
```

`main.py` loads config, initialises logging, optionally starts a config file watcher, then dispatches to the appropriate transport.

`config.py` merges settings in this order (later wins): hardcoded defaults → `~/.mcp-stdio-bridge.yaml` → local `config.yaml` → explicit `--config` path → `MCP_*` env vars → CLI flags.

`middleware.py` provides `APIKeyMiddleware` (timing-safe comparison), `SecurityHeadersMiddleware` (CSP, HSTS, X-Frame-Options), and `RateLimitMiddleware` (per-IP sliding window), all used only by the SSE transport.

## Testing notes

Always pass `--timeout=10` (via `pytest-timeout`) when running tests. SSE transport tests that pass auth and reach `handle_sse` will spawn a real subprocess and block indefinitely if the handler is not mocked — the timeout flag is the safety net for any such hang.

## Key behaviours to be aware of

- **stdout is sacred in stdio mode.** All logging is routed to `sys.stderr`. Never add `print()` or any write to `sys.stdout` in the code paths active during stdio transport — it corrupts the JSON-RPC framing.
- **Wrapper mode never uses `shell=True`.** Arguments are parsed with `shlex` and passed as a list to `anyio.run_process`. Security filters (allowlist/denylist regex + `..` blocking) run before execution.
- **Config groups** (`groups` + `apply`) let commands share security policies without duplication. List fields (`forbidden_patterns`, etc.) are unioned across all applied groups and per-command values; scalar fields (`timeout`, `cwd`) prefer the per-command value, falling back to the last applied group.
- **Environment scrubbing is on by default.** `config.py:prepare_env()` strips sensitive vars (API keys, cloud credentials) from the environment passed to subprocesses. The `env_allowlist` setting flips this to an explicit pass-through list.
- **`bandit` skips B104 (bind-all), B105 (password in key name), and B404 (subprocess import)** via `pyproject.toml`.
- **Dynamic config reload** (`--watch-config`) uses a file-watcher thread; only transport-agnostic settings (logging level, timeouts, etc.) are hot-reloadable without restart.
