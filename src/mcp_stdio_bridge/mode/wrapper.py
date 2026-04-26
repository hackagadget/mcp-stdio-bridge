# SPDX-License-Identifier: Unlicense
"""
Command Wrapper Module
======================

Hosts an internal MCP server that dynamically wraps standard CLI utilities
as MCP tools. Implements security sandboxing by enforcing forbidden
argument prefixes, regex patterns, and execution timeouts.
"""
import anyio
import shlex
import subprocess
import emoji
import re
import os
from typing import Any, Dict, List
from mcp.server import Server
import mcp.types as types
from ..config import settings, prepare_env
from ..logging_utils import logger

_LIST_FIELDS = frozenset({
    "forbidden_patterns", "forbidden_args", "allowed_args", "allowed_patterns"
})


def apply_groups(cmd_config: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    """Return effective command config with named groups merged in via the `apply` key.

    List fields are unioned (groups first, in apply order, then per-command).
    Scalar fields: per-command wins; last applied group wins among groups.
    """
    apply_names = cmd_config.get("apply", [])
    if not apply_names:
        return cmd_config

    effective: Dict[str, Any] = {}

    for group_name in apply_names:
        if group_name not in groups:
            logger.warning(
                f"Config group '{group_name}' referenced by command "
                f"'{cmd_config.get('name')}' does not exist. Skipping."
            )
            continue
        for field, value in groups[group_name].items():
            if field in _LIST_FIELDS:
                existing = effective.get(field, [])
                for item in value:
                    if item not in existing:
                        existing.append(item)
                effective[field] = existing
            else:
                effective[field] = value

    for field, value in cmd_config.items():
        if field == "apply":
            continue
        if field in _LIST_FIELDS:
            existing = effective.get(field, [])
            for item in value:
                if item not in existing:
                    existing.append(item)
            effective[field] = existing
        else:
            effective[field] = value

    return effective


def create_wrapper_server() -> Server:
    """
    Factory function to create an internal MCP server that wraps configured CLI tools.

    Returns:
        Server: A configured MCP server instance with tools registered
                based on the 'wrapped_commands' setting.
    """
    server: Server[Any, Any] = Server(name="mcp-command-wrapper")

    def get_validated_tools() -> Dict[str, Any]:
        """Dynamically generate and validate tools map from current settings."""
        tools_map = {}
        groups = settings.get("groups", {})
        for cmd_config in settings.get("wrapped_commands", []):
            effective = apply_groups(cmd_config, groups)
            name = effective["name"]
            forbidden_args = effective.get("forbidden_args", [])
            allowed_args = effective.get("allowed_args", [])
            allowed_patterns = effective.get("allowed_patterns", [])

            if (allowed_args or allowed_patterns) and forbidden_args:
                logger.error(
                    f"Command '{name}' has both allowed_args and forbidden_args "
                    f"security rules. Skipping."
                )
                continue
            tools_map[name] = effective
        return tools_map

    @server.list_tools()  # type: ignore[misc, no-untyped-call, untyped-decorator]
    async def handle_list_tools() -> list[types.Tool]:
        """
        MCP handler to list available tools.
        """
        tools_map = get_validated_tools()
        return [
            types.Tool(
                name=c["name"],
                description=c["description"],
                inputSchema={
                    "type": "object",
                    "properties": {
                        "subcommand": {
                            "type": "string",
                            "description": "Arguments to pass to the command."
                        }
                    },
                    "required": ["subcommand"]
                }
            )
            for c in settings.get("wrapped_commands", [])
            if c["name"] in tools_map
        ]

    @server.call_tool()  # type: ignore[misc, untyped-decorator]
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> List[types.TextContent]:
        """
        MCP handler to execute a specific tool call.
        """
        tools_map = get_validated_tools()
        if name not in tools_map:
            raise ValueError(f"Unknown tool: {name}")

        cmd_config = tools_map[name]
        subcommand = arguments.get("subcommand", "")
        base_cmd = cmd_config["command"]
        forbidden_args = cmd_config.get("forbidden_args", [])
        forbidden_patterns = cmd_config.get("forbidden_patterns", [])
        allowed_args = cmd_config.get("allowed_args", [])
        allowed_patterns = cmd_config.get("allowed_patterns", [])
        work_dir = cmd_config.get("cwd")
        custom_env = cmd_config.get("env", {})
        time_limit = cmd_config.get("timeout", 30)

        # 1. Sanitize and split input safely into a list to prevent shell injection.
        try:
            args = shlex.split(subcommand)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error parsing subcommand: {e}")]

        cmd_string = " ".join(args).strip()
        cmd_string_lower = cmd_string.lower()

        # 2. Path Sanitization: Prevent directory traversal if a working directory is set.
        if work_dir:
            for arg in args:
                if ".." in arg or (os.path.isabs(arg) and not arg.startswith(work_dir)):
                     logger.warning(emoji.emojize(f":warning: Blocked path traversal attempt: "
                                                  f"'{arg}'"))
                     return [types.TextContent(type="text", text="Error: Path traversal or "
                                               "unauthorized absolute path detected.")]

        # 3. Safety Filter (Denylist): Block forbidden prefixes.
        if forbidden_args:
            for restricted in forbidden_args:
                if cmd_string_lower.startswith(restricted.lower().strip()):
                    logger.warning(emoji.emojize(f":warning: Blocked restricted command: "
                                                 f"'{cmd_string}' (matched prefix '{restricted}')"))
                    return [types.TextContent(type="text", text=f"Error: The command prefix "
                                              f"'{restricted}' is restricted for security.")]

        # 4. Safety Filter (Allowlist): Only allow specific prefixes or patterns.
        if allowed_args or allowed_patterns:
            is_allowed = False

            # Check prefixes
            for permitted in allowed_args:
                if cmd_string_lower.startswith(permitted.lower().strip()):
                    is_allowed = True
                    break

            # Check patterns
            if not is_allowed and allowed_patterns:
                for pattern in allowed_patterns:
                    if re.search(pattern, cmd_string, re.IGNORECASE):
                        is_allowed = True
                        break

            if not is_allowed:
                logger.warning(emoji.emojize(f":warning: Blocked unauthorized command: "
                                             f"'{cmd_string}'"))
                return [types.TextContent(type="text", text="Error: The provided subcommand is "
                                          "not in the allowed list for this tool.")]

        # 5. Safety Filter (Patterns): Always applied last as a final veto, regardless of
        #    whether the tool uses an allowlist or denylist approach.
        if forbidden_patterns:
            for pattern in forbidden_patterns:
                if re.search(pattern, cmd_string, re.IGNORECASE):
                    logger.warning(emoji.emojize(f":warning: Blocked restricted command: "
                                                 f"'{cmd_string}' (matched pattern '{pattern}')"))
                    return [types.TextContent(type="text", text="Error: The subcommand matches "
                                              "a restricted security pattern.")]

        # 6. Execution: Assemble and run the command with capture.
        full_command = [base_cmd] + args
        logger.info(f"Executing wrapped command: {' '.join(full_command)}")

        # Prepare environment: Start with a sanitized base and overlay tool-specific variables.
        full_env = prepare_env()
        if custom_env:
            full_env.update(custom_env)

        try:
            # Run the process using anyio's async runner.
            with anyio.fail_after(time_limit):
                result = await anyio.run_process(
                    full_command,
                    check=False,  # Allow non-zero exit codes to return their output normally.
                    cwd=work_dir,
                    env=full_env,
                    stderr=subprocess.STDOUT  # Merge stderr to simplify response for the LLM.
                )

                output = result.stdout.decode().strip()
                if not output:
                    output = "Command executed successfully (no output)."

                return [types.TextContent(type="text", text=output)]

        except TimeoutError:
            return [types.TextContent(type="text", text=f"Error: Command timed out after "
                                      f"{time_limit} seconds.")]
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return [types.TextContent(type="text", text=f"System Error during execution: {str(e)}")]

    return server
