# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-04-28

### Added

- **Global Working Directory**: Added support for a top-level `cwd` setting and a `--cwd` CLI
  flag, providing a fallback working directory for all subprocesses in both proxy and wrapper
  modes.

## [1.3.0] - 2026-04-28

### Added

- **API Key Generator**: Added `--generate-api-key` CLI flag that prints a cryptographically
  random URL-safe Base64 key (256-bit entropy) and exits, making it easy to generate a value
  for the `api_key` config field without starting the bridge.
- **Config Validator**: Added `--check-config` flag (modelled on `nginx -t`) that validates
  configuration without starting the bridge. Each config file is parsed and validated against
  the bundled JSON schema; the merged result is then checked for semantic errors (missing
  `command`, incomplete SSL pair, etc.) and warnings (SSE-only options in stdio mode,
  conflicting env lists). Exits 0 on success, 1 on any error.
- **Warnings as Errors**: Added `--warnings-as-errors` flag (used with `--check-config`) that
  promotes all warnings to errors, enabling strict validation in CI or systemd/rc.d
  `ExecStartPre=` checks.
- **Config Generator**: Added `--generate-config` flag that prints a minimal YAML config
  built from the supplied CLI flags (only settings that differ from their defaults are
  emitted). When combined with `--generate-api-key`, the generated key is embedded in the
  `api_key` field of the output instead of being printed separately.
- **Client Config Generator**: Added `--generate-client-config CLIENT` flag that produces
  a ready-to-paste JSON snippet for a target MCP client (`claude-desktop`, `claude-code`,
  `cursor`, `gemini`, `vscode`, `copilot`). The snippet is tailored to the resolved
  transport — stdio transport yields a `command`/`args` entry; SSE transport yields a `url`
  and optional `X-API-Key` headers block. The client's conventional config file path and a
  merge note are printed to stderr alongside a format-stability warning.
- **Output Flag**: Added `--output FILE` / `-o FILE` flag to write `--generate-client-config`
  output directly to a file (the resolved absolute path is echoed to stderr) instead of
  stdout.
- **Standalone Integration Tests**: Added a suite of end-to-end integration tests in
  `standalone_tests/` for validating SSH, Docker, and various transport scenarios.

### Changed

- **SSE Transport Refactoring**: Refactored the SSE transport implementation into separate
  proxy and wrapper modules (`sse_proxy.py` and `sse_wrapper.py`) for better maintainability
  and clearer separation of concerns.
- **ASGI Middleware**: Converted `APIKeyMiddleware`, `SecurityHeadersMiddleware`, and
  `RateLimitMiddleware` from Starlette `BaseHTTPMiddleware` to pure ASGI middleware. This
  improves reliability and eliminates potential stream-interruption issues when using
  SSE transport.

### Fixed

- **Expanded Environment Scrubbing**: The default `env_denylist` now includes a much broader
  range of sensitive variables, including `AWS_SESSION_TOKEN`, `AZURE_CLIENT_SECRET`,
  `GOOGLE_APPLICATION_CREDENTIALS`, `DB_PASSWORD`, and `DATABASE_URL`.
- **Wrapper Command String Splitting**: `command` values containing spaces (e.g.
  `"wp core"`) are now split via `shlex.split` before being passed to the subprocess,
  producing `["wp", "core", <args>]` instead of `["wp core", <args>]`. The latter caused
  `FileNotFoundError` on Linux because no executable named `"wp core"` (with a space)
  exists on `PATH`. The list form (`command: ["wp", "core"]`) continues to work as before.
- **Clean Shutdown on Windows**: `Ctrl+C` no longer prints an `ExceptionGroup` traceback when
  using SSE transport. Uvicorn handles the first `SIGINT` itself and re-raises it via
  `signal.raise_signal()` after cleanup, which caused a `KeyboardInterrupt` to surface inside
  the anyio task group and get wrapped in a `BaseExceptionGroup`. The top-level exception
  handler now suppresses groups composed entirely of `KeyboardInterrupt`.
- **Windows Compatibility Fix**: Added a workaround for `rich.box` encoding crashes on
  certain Windows terminal environments by mocking the module if it fails to load safely.
- **Improved Stdio Reliability**: Enabled line-buffering on `sys.stdout` to ensure prompt
  delivery of JSON-RPC messages and added detailed traceback reporting for fatal start-up
  errors.

### Documentation

- **MCP Client Configuration**: Added comprehensive documentation in `docs/configuration.md` for
  generating and using client-specific configuration snippets.
- **WP-CLI Example**: Greatly expanded `examples/wp-cli-wrapper.yaml` with a production-ready
  suite of WordPress management tools, including security groups and granular argument
  filtering.
- **Deployment & Integration**: Added detailed instructions for the new standalone integration
  test suite in `docs/deployment.md`.

## [1.2.2] - 2026-04-26

### Added

- **Version Flag**: Added `--version` CLI flag to display the application version and exit.

### Fixed

- **Stream Integrity**: Redirected configuration warnings and error messages to `sys.stderr`. This prevents corruption of the JSON-RPC stream when operating in Stdio transport mode.
- **CLI Logic**: Improved boolean flag handling in `parse_args` to avoid spurious "option ignored" warnings when using Stdio transport if the flags were not explicitly provided.

## [1.2.1.post1] - 2026-04-26

### Fixed

- Resolved minor style issues and unused imports in the test suite.

## [1.2.1] - 2026-04-26

### Fixed

- **Graceful Shutdown**: Added `SIGTERM` handler on POSIX systems to trigger clean exit via `KeyboardInterrupt`.
- **Subprocess Cleanup**: Enhanced SSE and Stdio transports with a 2-second wait timeout and `kill()` fallback for zombie processes.
- **Process Ownership**: Centralized subprocess termination in the transport layer for better reliability.
- **Code Quality**: Achieved 100% test coverage across all modules and resolved all `bandit` and `ruff` linting issues.

## [1.2.0] - 2026-04-26

### Added

- **Global Rate Limiting** (SSE only): Throttling mechanism to protect against DoS or resource abuse.
  - Configurable via `rate_limit_requests` and `rate_limit_window`.
  - Uses a sliding-window algorithm with per-IP buckets.
  - Respects `X-Forwarded-For` for clients behind reverse proxies.
- Rate limiting settings added to `schema.json` and `config.example.yaml`.

## [1.1.0] - 2026-04-26

### Added

- **Config groups** (`groups` + `apply`): named presets defined once at the top level of
  `config.yaml` and applied to individual wrapped commands via the `apply` key. Eliminates
  the need to duplicate `forbidden_patterns`, `forbidden_args`, `timeout`, `cwd`, or `env`
  across every command entry.
  - List fields (`forbidden_patterns`, `forbidden_args`, `allowed_args`, `allowed_patterns`)
    are unioned across all applied groups and any per-command values.
  - Scalar fields (`timeout`, `cwd`, `env`) follow last-group-wins ordering, with
    per-command values always taking final precedence.
  - Unknown group names log a warning and are skipped without affecting the tool.
  - The existing allowlist/denylist mutual-exclusivity check runs after group expansion.
- `groups` added to `schema.json` (top-level object) and `apply` added to the
  `wrapped_commands` item schema.

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

[1.3.0]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.3.0
[1.2.2]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.2.2
[1.2.1.post1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.2.1.post1
[1.2.1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.2.1
[1.2.0]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.2.0
[1.1.0]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.1.0
[1.0.3.post1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.3.post1
[1.0.3]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.3
[1.0.2]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.2
[1.0.1.post1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.1.post1
[1.0.1]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.1
[1.0.0]: https://github.com/hackagadget/mcp-stdio-bridge/releases/tag/v1.0.0
