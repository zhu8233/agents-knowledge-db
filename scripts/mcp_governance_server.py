#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp_governance_backend import GovernanceBackend, SERVER_INFO, SUPPORTED_PROTOCOL_VERSIONS


def read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def success_response(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agents Knowledge DB MCP governance server over stdio.")
    parser.add_argument("target_vault", help="Path to the governed data vault")
    parser.add_argument("--subject-id", required=True, help="Authenticated subject identifier")
    parser.add_argument("--auth-mode", required=True, choices=["oauth", "token"], help="Authentication mode")
    args = parser.parse_args()

    backend = GovernanceBackend(Path(args.target_vault), subject_id=args.subject_id, auth_mode=args.auth_mode)

    while True:
        message = read_message()
        if message is None:
            break

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})

        if method == "notifications/initialized":
            continue

        try:
            if method == "initialize":
                requested_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
                protocol_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
                result = {
                    "protocolVersion": protocol_version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": SERVER_INFO,
                }
                write_message(success_response(request_id, result))
                continue

            if method == "ping":
                write_message(success_response(request_id, {}))
                continue

            if method == "tools/list":
                write_message(success_response(request_id, {"tools": backend.list_tools()}))
                continue

            if method == "tools/call":
                name = params["name"]
                arguments = params.get("arguments", {})
                write_message(success_response(request_id, backend.call_tool(name, arguments)))
                continue

            if method == "resources/list":
                write_message(success_response(request_id, {"resources": backend.list_resources()}))
                continue

            if method == "resources/read":
                write_message(success_response(request_id, backend.read_resource(params["uri"])))
                continue

            if method == "prompts/list":
                write_message(success_response(request_id, {"prompts": backend.list_prompts()}))
                continue

            if method == "prompts/get":
                write_message(success_response(request_id, backend.get_prompt(params["name"], params.get("arguments", {}))))
                continue

            write_message(error_response(request_id, -32601, f"Method not found: {method}"))
        except KeyError as exc:
            write_message(error_response(request_id, -32602, f"Missing parameter: {exc}"))
        except ValueError as exc:
            write_message(error_response(request_id, -32602, str(exc)))
        except Exception as exc:  # pragma: no cover
            write_message(error_response(request_id, -32000, str(exc)))


if __name__ == "__main__":
    main()
