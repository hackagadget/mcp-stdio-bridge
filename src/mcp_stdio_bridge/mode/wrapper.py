# SPDX-License-Identifier: Unlicense
"""
Command Wrapper Module
======================
Hosts an internal MCP server that dynamically wraps standard CLI utilities
as MCP tools.
"""

import anyio
import shlex
import subprocess
import re
import sys
import asyncio
from typing import Any, Dict, List
from ..config import settings, prepare_env
from ..logging_utils import logger

_LIST_FIELDS = frozenset(
    {"forbidden_patterns", "forbidden_args", "allowed_args", "allowed_patterns"}
)


def apply_groups(cmd_config: Dict[str, Any], groups: Dict[str, Any]) -> Dict[str, Any]:
    apply_names = cmd_config.get("apply", [])
    if not apply_names:
        return cmd_config
    effective: Dict[str, Any] = {}
    for group_name in apply_names:
        if group_name not in groups:
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


def create_wrapper_server() -> Any:
    """Factory function to create an internal MCP server that wraps CLI tools."""
    # Lazy load MCP SDK
    from mcp.server import Server
    import mcp.types as types

    server: Server[Any, Any] = Server(name="mcp-command-wrapper")

    def get_validated_tools() -> Dict[str, Any]:
        tools_map = {}
        groups = settings.get("groups", {})
        for cmd_config in settings.get("wrapped_commands", []):
            effective = apply_groups(cmd_config, groups)
            name = effective["name"]
            tools_map[name] = effective
        return tools_map

    async def list_tools_impl() -> List[types.Tool]:
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
                            "description": "Arguments to pass to the command.",
                        }
                    },
                    "required": ["subcommand"],
                },
            )
            for c in settings.get("wrapped_commands", [])
            if c["name"] in tools_map
        ]

    async def call_tool_impl(name: str, arguments: dict[str, Any]) -> List[types.TextContent]:
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
        work_dir = cmd_config.get("cwd") or settings.get("cwd")
        custom_env = cmd_config.get("env", {})
        time_limit = cmd_config.get("timeout", 30)

        try:
            args = shlex.split(subcommand)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error parsing subcommand: {e}")]

        cmd_string = " ".join(args).strip()
        cmd_string_lower = cmd_string.lower()

        if forbidden_args:
            for restricted in forbidden_args:
                if cmd_string_lower.startswith(restricted.lower().strip()):
                    return [
                        types.TextContent(
                            type="text",
                            text=(
                        f"Error: The command prefix '{restricted}'"
                        " is restricted for security."
                    ),
                        )
                    ]

        if (allowed_args or allowed_patterns) and cmd_string:
            is_allowed = False
            for permitted in allowed_args:
                if cmd_string_lower.startswith(permitted.lower().strip()):
                    is_allowed = True
                    break
            if not is_allowed and allowed_patterns:
                for pattern in allowed_patterns:
                    if re.search(pattern, cmd_string, re.IGNORECASE):
                        is_allowed = True
                        break
            if not is_allowed:
                return [
                    types.TextContent(
                        type="text",
                        text=(
                            "Error: The provided subcommand is not in"
                            " the allowed list for this tool."
                        ),
                    )
                ]

        if forbidden_patterns:
            for pattern in forbidden_patterns:
                if re.search(pattern, cmd_string, re.IGNORECASE):
                    return [
                        types.TextContent(
                            type="text",
                            text="Error: The subcommand matches a restricted security pattern.",
                        )
                    ]

        if isinstance(base_cmd, list):
            full_command = base_cmd + args
        else:
            full_command = shlex.split(base_cmd) + args

        logger.info(f"Executing wrapped command: {' '.join(full_command)}")

        full_env = prepare_env()
        if custom_env:
            full_env.update(custom_env)

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    *full_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL,
                    cwd=work_dir,
                    env=full_env,
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=time_limit)
                    output = stdout.decode().strip()
                except asyncio.TimeoutError:
                    if proc.returncode is None:
                        proc.terminate()
                    return [
                        types.TextContent(
                            type="text", text=f"Error: Command timed out after {time_limit}s"
                        )
                    ]
            else:
                with anyio.fail_after(time_limit):  # pragma: no cover
                    result = await anyio.run_process(
                        full_command,
                        check=False,
                        cwd=work_dir,
                        env=full_env,
                        stderr=subprocess.STDOUT,
                    )
                    output = result.stdout.decode().strip()

            if not output:  # pragma: no cover
                output = "Command executed successfully (no output)."
            return [types.TextContent(type="text", text=output)]

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return [types.TextContent(type="text", text=f"System Error during execution: {str(e)}")]

    # Register handlers
    server.list_tools()(list_tools_impl)  # type: ignore[no-untyped-call]
    server.call_tool()(call_tool_impl)  # type: ignore[no-untyped-call]

    # Exposed for testing
    server.get_tools = list_tools_impl  # type: ignore
    server.call_tool_logic = call_tool_impl  # type: ignore

    return server
