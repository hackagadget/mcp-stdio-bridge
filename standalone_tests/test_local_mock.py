# SPDX-License-Identifier: Unlicense
"""
Test Local Mock
===============
Runs the mcp-stdio-bridge locally in stdio transport mode,
wrapping the mock_wp.py script.
"""

import asyncio
import json
import sys
import os
from typing import Any

from generate_local_config import generate


async def main() -> None:
    config_path = generate()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mock_script = os.path.join(base_dir, "mock_wp.py")
    mock_script_abs = os.path.abspath(mock_script).replace("\\", "/")

    print("[*] Starting mcp-stdio-bridge with forward-slash paths...")

    env = os.environ.copy()
    project_root = os.getcwd()
    if os.path.basename(project_root) == "standalone_tests":
        project_root = os.path.dirname(project_root)

    env["PYTHONPATH"] = os.path.join(project_root, "src").replace("\\", "/")
    env["PYTHONUNBUFFERED"] = "1"

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_stdio_bridge.main",
        "--config",
        config_path,
        "--transport",
        "stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
        env=env,
        cwd=project_root,
    )

    if process.stdin is None or process.stdout is None:
        return
    stdin = process.stdin
    stdout = process.stdout

    async def send(req: dict[str, Any]) -> None:
        data = json.dumps(req) + "\n"
        stdin.write(data.encode())
        await stdin.drain()
        print(f"--> SEND ({req.get('method', 'response')} id={req.get('id')})")

    async def receive(timeout: float = 5.0) -> dict[str, Any] | None:
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
            if line:
                try:
                    resp: dict[str, Any] = json.loads(line)
                    method = resp.get("method", "response")
                    print(f"<-- RECV ({method} id={resp.get('id')})")
                    return resp
                except json.JSONDecodeError:
                    print(f"[!] Bridge Output (non-JSON): {line.decode().strip()}")
        except asyncio.TimeoutError:
            print(f"[!] Timeout: No response from bridge after {timeout}s")
        return None

    try:
        # 1. Initialize
        print("\n[STEP 1: INITIALIZATION]")
        await send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mock-test-client", "version": "1.0.0"},
                },
            }
        )
        await receive()

        # 2. List Tools
        print("\n[STEP 2: DISCOVERY]")
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
                    "arguments": {"subcommand": f"{mock_script_abs} core version"},
                },
            }
        )
        resp = await receive()
        if resp and "result" in resp:
            print(f"RESULT: {resp['result']['content'][0]['text']}")

        # 4. Call forbidden command
        print("\n[STEP 4: SECURITY FILTER TEST]")
        await send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "wp_plugin",
                    "arguments": {"subcommand": f"{mock_script_abs} plugin install akismet"},
                },
            }
        )
        resp = await receive()
        if resp and "result" in resp:
            print(f"RESULT: {resp['result']['content'][0]['text']}")

    finally:
        print("\n[*] Terminating bridge...")
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[!] Bridge did not exit gracefully, killing...")
                process.kill()
        print("[*] Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
