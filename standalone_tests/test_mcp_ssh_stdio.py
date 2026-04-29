# SPDX-License-Identifier: Unlicense
"""
Test MCP SSH Stdio
==================
Tests the MCP pipeline by connecting directly to a remote host via SSH.
"""

import asyncio
import json
import sys
import argparse
from typing import Any


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP over SSH Stdio")
    parser.add_argument("--host", required=True, help="SSH host (e.g., user@192.168.1.10)")
    parser.add_argument("--config", required=True, help="Path to config.yaml on the remote host")
    parser.add_argument("--ssh-args", help="Additional SSH arguments (e.g., '-p 2222 -s')")
    parser.add_argument(
        "--mock-script",
        default="standalone_tests/mock_wp.py",
        help="Path to mock_wp.py on the remote host (must match the bridge config's allowed_args)",
    )
    args = parser.parse_args()
    mock_script = args.mock_script

    remote_cmd = f"mcp-stdio-bridge --transport stdio --config {args.config}"

    print(f"[*] Connecting to {args.host}...")

    ssh_cmd = ["ssh"]
    if args.ssh_args:
        import shlex

        ssh_cmd.extend(shlex.split(args.ssh_args))
    ssh_cmd.extend([args.host, remote_cmd])

    print(f"[*] Executing: {' '.join(ssh_cmd)}")

    try:
        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,
        )
    except Exception as e:
        print(f"[!] Failed to start SSH process: {e}")
        return

    if process.stdin is None or process.stdout is None:
        return
    stdin = process.stdin
    stdout = process.stdout

    async def send(req: dict[str, Any]) -> None:
        data = json.dumps(req) + "\n"
        stdin.write(data.encode())
        await stdin.drain()
        print(f"--> SEND ({req.get('method', 'response')} id={req.get('id')})")

    async def receive(timeout: float = 10.0) -> dict[str, Any] | None:
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
            if line:
                try:
                    resp: dict[str, Any] = json.loads(line)
                    print(f"<-- RECV ({resp.get('method', 'response')} id={resp.get('id')})")
                    result = resp.get("result", {})
                    if "content" in result:
                        for item in result["content"]:
                            print(f"    CONTENT: {item.get('text', '')}")
                    elif "tools" in result:
                        for tool in result["tools"]:
                            print(f"    TOOL: {tool.get('name')} -- {tool.get('description', '')}")
                    elif result:
                        print(f"    RESULT: {json.dumps(result, indent=None)}")
                    if "error" in resp:
                        print(f"    ERROR: {resp['error']}")
                    return resp
                except json.JSONDecodeError:
                    print(f"[!] Failed to decode JSON: {line.decode().strip()}")
        except asyncio.TimeoutError:
            print(f"[!] Timeout: No response via SSH after {timeout}s")
        return None

    try:
        # 1. Initialize
        print("\n[STEP 1: INITIALIZATION]")
        print("WHAT: Sending 'initialize' request.")
        print("WHY:  Negotiate protocol with the remote bridge via SSH tunnel.")
        await send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ssh-test-client", "version": "1.0.0"},
                },
            }
        )
        await receive()

        # 2. List Tools
        print("\n[STEP 2: DISCOVERY]")
        print("WHAT: Sending 'tools/list' request.")
        await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        await receive()

        # 3. Call wp_core version
        print("\n[STEP 3: VALID COMMAND EXECUTION]")
        await send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "wp_core",
                    "arguments": {"subcommand": f"{mock_script} core version"},
                },
            }
        )
        await receive()

        # 4. Call forbidden command
        print("\n[STEP 4: SECURITY FILTER TEST]")
        await send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "wp_plugin",
                    "arguments": {"subcommand": f"{mock_script} plugin install akismet"},
                },
            }
        )
        await receive()

    finally:
        print("\n[*] Closing SSH connection...")
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[!] SSH did not exit gracefully, killing...")
                process.kill()
        print("[*] Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
