# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3.post1] - 2026-04-26

### Fixed

- Removed unused `forbidden_patterns` variable from the conflict-guard block in
  `get_validated_tools()` (ruff F841).
- Wrapped long `logger.error` call and test line to stay within the
  100-character line limit (ruff E501).

## [1.0.3] - 2026-04-26

### Changed

- `forbidden_patterns` is now applied as a final veto after all other security checks,
  making it composable with allowlist tools (`allowed_args` / `allowed_patterns`). Previously,
  combining any forbidden rule with any allowed rule on the same tool caused the tool to be
  skipped entirely. The mutual-exclusivity guard now only applies to `forbidden_args` vs.
  `allowed_args` / `allowed_patterns`.

## [1.0.2] - 2026-04-26

### Fixed

- `transport/` and `mode/` subpackages were missing from installed distributions
  due to an explicit `packages` list in `pyproject.toml`; switched to automatic
  package discovery so all subpackages are included.

## [1.0.1.post1] - 2026-04-20

### Fixed

- README installation command corrected to `pip install mcp-stdio-bridge`.

## [1.0.1] - 2026-04-20

### Fixed

- Subprocess is now terminated cleanly when `bridge_streams` exits.
- Release workflow split into independent `build`, `github-release`, and
  `publish-to-pypi` jobs with PyPI Trusted Publishing (OIDC).

## [1.0.0] - 2026-04-19

### Added

- **SSE transport** — HTTP + Server-Sent Events gateway via Starlette/Uvicorn with API key
  authentication, configurable connection limits, and optional SSL/TLS (mTLS supported).
- **Stdio transport** — raw stdin/stdout transport; all logging is routed to stderr to avoid
  corrupting the JSON-RPC framing.
- **Proxy mode** — spawns one subprocess per connection and bridges streams bidirectionally;
  `ActivityMonitor` handles idle-timeout auto-termination.
- **Command-wrapper mode** — hosts an internal MCP server where each `wrapped_commands` entry
  becomes an MCP tool; arguments are parsed with `shlex` (no `shell=True`) and validated
  against per-tool allowlist/denylist regex rules before execution.
- **Security middleware** — `APIKeyMiddleware` (timing-safe comparison) and
  `SecurityHeadersMiddleware` (CSP, HSTS, X-Frame-Options) for the SSE transport.
- **Environment scrubbing** — sensitive variables (API keys, cloud credentials) are stripped
  from subprocess environments by default; `env_allowlist` enables explicit pass-through.
- **Path traversal protection** — blocks `..` segments and unauthorized absolute paths when
  a working directory is configured for a wrapped command.
- **Dynamic config reload** — `--watch-config` flag hot-reloads transport-agnostic settings
  (log level, timeouts, etc.) without restarting.
- **Layered configuration** — settings merge in order: built-in defaults → `~/.mcp-stdio-bridge.yaml`
  → local `config.yaml` → `--config` path → `MCP_*` environment variables → CLI flags.
- **Docker support** — `Dockerfile` and `docker-compose.yaml` included.
- **100% test coverage** across all modules.

[1.0.3.post1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.3.post1
[1.0.3]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.3
[1.0.2]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.2
[1.0.1.post1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.1.post1
[1.0.1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.1
[1.0.0]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.0
