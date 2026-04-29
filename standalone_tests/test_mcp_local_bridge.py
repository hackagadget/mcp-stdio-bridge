# SPDX-License-Identifier: Unlicense
"""
Test MCP Local Bridge (SSE)
===========================
Tests the MCP pipeline by connecting to a LOCAL mcp-stdio-bridge
running in SSE mode.
"""

import asyncio
import json
import argparse
import httpx
import os
import sys
import traceback
from typing import Any


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test MCP over Local SSE Bridge")
    parser.add_argument(
        "--url", default="http://localhost:8000", help="Base URL of the local bridge"
    )
    parser.add_argument("--api-key", help="API Key (if configured)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    mock_script = os.path.join(base_dir, "mock_wp.py").replace("\\", "/")

    headers = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    print(f"[*] Connecting to SSE at {args.url}/sse ...")

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        try:
            async with client.stream("GET", f"{args.url}/sse") as response:
                if response.status_code != 200:
                    print(f"[!] Connection failed with status {response.status_code}")
                    return

                endpoint = None
                stop_event = asyncio.Event()
                expected_responses = {1, 2, 3, 4}
                received_responses = set()

                async def read_sse() -> None:
                    nonlocal endpoint
                    try:
                        print("[*] SSE Stream opened. Waiting for events...")
                        event_type = None
                        async for line in response.aiter_lines():
                            if stop_event.is_set():
                                break
                            line = line.strip()
                            if not line:
                                continue

                            if line.startswith("event: "):
                                event_type = line[7:]
                            elif line.startswith("data: "):
                                data_str = line[6:]
                                if event_type == "endpoint":
                                    endpoint = data_str
                                    print(f"[*] Received endpoint: {endpoint}")
                                elif event_type == "message" or event_type is None:
                                    try:
                                        data = json.loads(data_str)
                                        req_id = data.get("id")
                                        if req_id:
                                            print(f"<-- RECV SSE (response id={req_id})")
                                            received_responses.add(req_id)
                                            result = data.get("result")
                                            error = data.get("error")
                                            if result is not None:
                                                if "content" in result:
                                                    text = result["content"][0].get("text", "")
                                                    print(f"    RESULT: {text}")
                                                elif "tools" in result:
                                                    names = [t["name"] for t in result["tools"]]
                                                    print(f"    TOOLS: {', '.join(names)}")
                                                elif "serverInfo" in result:
                                                    info = result["serverInfo"]
                                                    name = info.get("name")
                                                    ver = info.get("version")
                                                    print(f"    SERVER: {name} v{ver}")
                                                else:
                                                    print(f"    RESULT: {result}")
                                            elif error is not None:
                                                print(f"    ERROR: {error}")
                                            if expected_responses.issubset(received_responses):
                                                stop_event.set()
                                    except json.JSONDecodeError:
                                        print(f"[!] Failed to decode data: {data_str}")
                                event_type = None
                    except Exception as e:
                        if not stop_event.is_set():
                            print(f"[!] SSE Read Error: {e}")
                    finally:
                        stop_event.set()

                async def send_requests() -> None:
                    try:
                        while endpoint is None:
                            if stop_event.is_set():
                                return
                            await asyncio.sleep(0.1)

                        post_url = f"{args.url}{endpoint}"

                        async def call_mcp(
                            method: str, params: dict[str, Any], req_id: int
                        ) -> None:
                            payload = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "method": method,
                                "params": params,
                            }
                            print(f"--> SEND POST ({method} id={req_id})")
                            await client.post(post_url, json=payload)

                        print("\n[STEP 1: INITIALIZATION]")
                        await call_mcp(
                            "initialize",
                            {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {},
                                "clientInfo": {"name": "local-test-client", "version": "1.0.0"},
                            },
                            1,
                        )

                        print("\n[STEP 2: DISCOVERY]")
                        await call_mcp("tools/list", {}, 2)

                        print("\n[STEP 3: VALID COMMAND EXECUTION]")
                        await call_mcp(
                            "tools/call",
                            {
                                "name": "wp_core",
                                "arguments": {"subcommand": f"{mock_script} core version"},
                            },
                            3,
                        )

                        print("\n[STEP 4: SECURITY FILTER TEST]")
                        await call_mcp(
                            "tools/call",
                            {
                                "name": "wp_plugin",
                                "arguments": {
                                    "subcommand": f"{mock_script} plugin install akismet"
                                },
                            },
                            4,
                        )
                    except Exception as e:
                        print(f"[!] Request Error: {e}")
                        stop_event.set()

                async with asyncio.TaskGroup() as tg:  # type: ignore[attr-defined]
                    tg.create_task(read_sse())
                    tg.create_task(send_requests())
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        missing = expected_responses - received_responses
                        print(f"\n[!] Test timed out. Missing responses for IDs: {missing}")
                        stop_event.set()  # Allow read_sse task to exit
                        os._exit(1)

        except Exception as e:
            print(f"\n[!] Error during execution: {e}")
            traceback.print_exc()
            sys.exit(1)

    print("\n[*] Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
