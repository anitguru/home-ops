#!/usr/bin/env python3
"""Emit shell exports for social automation secrets via the Vault MCP HTTP endpoint.

This avoids storing X/Tavily/Postgres credentials in cron files. Normal mode prints
shell-quoted `export NAME=VALUE` lines intended for `eval "$(...)"`; check mode
prints only key presence and never secret values.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MCP_URL = "https://vault-mcp.anit.guru/mcp"

SECRET_MAP: dict[str, dict[str, str]] = {
    "secret/X": {
        "CONSUMER_KEY": "X_CONSUMER_KEY",
        "CONSUMER_SECRET": "X_CONSUMER_SECRET",
        "ACCESS_TOKEN": "X_ACCESS_TOKEN",
        "ACCESS_TOKEN_SECRET": "X_ACCESS_TOKEN_SECRET",
        "BEARER_TOKEN": "X_BEARER_TOKEN",
    },
    "secret/TAVILY": {
        "API_TOKEN": "TAVILY_API_TOKEN",
    },
    "secret/POSTGRES": {
        "DSN": "PG_DSN",
    },
}

PURPOSES: dict[str, list[str]] = {
    "post": [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "TAVILY_API_TOKEN",
        "PG_DSN",
    ],
    "engage": [
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "PG_DSN",
    ],
}


class McpError(RuntimeError):
    pass


def token_from_env_file() -> str | None:
    for env_path in (
        os.environ.get("HERMES_ENV_PATH"),
        str(Path.home() / ".hermes" / ".env"),
    ):
        if not env_path:
            continue
        path = Path(env_path).expanduser()
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        match = re.search(r"^VAULT_MCP_TOKEN=(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def parse_sse_json(raw: str) -> dict[str, Any]:
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return {}
    return json.loads("\n".join(data_lines))


def mcp_call(url: str, token: str, payload: dict[str, Any], session_id: str | None = None) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode(errors="replace")
            new_session = response.headers.get("Mcp-Session-Id") or session_id
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors="replace")
        raise McpError(f"Vault MCP HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise McpError(f"Vault MCP request failed: {exc}") from exc
    data = parse_sse_json(raw)
    if data.get("error"):
        raise McpError(json.dumps(data["error"], sort_keys=True))
    return data, new_session


def open_session(url: str, token: str) -> str | None:
    _, session_id = mcp_call(
        url,
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "social-actions-cron", "version": "1"},
            },
        },
    )
    # Best-effort initialized notification. Some servers return no body for notifications.
    try:
        mcp_call(
            url,
            token,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            session_id,
        )
    except Exception:
        pass
    return session_id


def read_secret(url: str, token: str, session_id: str | None, path: str) -> dict[str, Any]:
    response, _ = mcp_call(
        url,
        token,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_secret", "arguments": {"path": path}},
        },
        session_id,
    )
    content = response.get("result", {}).get("content", [])
    if not content:
        raise McpError(f"empty Vault MCP response for {path}")
    text = content[0].get("text", "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(f"non-JSON Vault secret response for {path}") from exc
    if not isinstance(data, dict):
        raise McpError(f"unexpected Vault secret shape for {path}")
    return data


def collect_env(url: str, token: str, purpose: str) -> dict[str, str]:
    session_id = open_session(url, token)
    values: dict[str, str] = {}
    for path, mapping in SECRET_MAP.items():
        data = read_secret(url, token, session_id, path)
        for secret_key, env_key in mapping.items():
            if secret_key in data and data[secret_key] is not None:
                values[env_key] = str(data[secret_key])
    needed = PURPOSES[purpose]
    return {name: values[name] for name in needed if name in values}


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit social automation env vars from Vault MCP")
    parser.add_argument("--purpose", choices=sorted(PURPOSES), required=True)
    parser.add_argument("--mcp-url", default=os.environ.get("VAULT_MCP_URL", DEFAULT_MCP_URL))
    parser.add_argument("--check", action="store_true", help="print presence only; never print secret values")
    args = parser.parse_args()

    token = os.environ.get("VAULT_MCP_TOKEN") or token_from_env_file()
    if not token:
        print("ERROR: VAULT_MCP_TOKEN not found in environment or ~/.hermes/.env", file=sys.stderr)
        return 1

    try:
        env = collect_env(args.mcp_url, token, args.purpose)
    except McpError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    missing = [name for name in PURPOSES[args.purpose] if not env.get(name)]
    if args.check:
        for name in PURPOSES[args.purpose]:
            print(f"{name}: {'set' if env.get(name) else 'missing'}")
        if missing:
            print("ERROR: missing required social automation secrets", file=sys.stderr)
            return 1
        return 0

    if missing:
        print(f"ERROR: missing required social automation secrets: {', '.join(missing)}", file=sys.stderr)
        return 1
    for key, value in env.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
