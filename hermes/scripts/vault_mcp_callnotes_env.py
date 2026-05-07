#!/usr/bin/env python3
"""Emit shell exports for callnotes secrets via the Vault MCP HTTP endpoint.

Normal mode prints shell-quoted `export NAME=VALUE` lines intended for
`eval "$(...)"`; check mode prints only presence/source and never secret values.
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
SECRET_CANDIDATES: dict[str, tuple[str, ...]] = {
    "secret/RCLONE": ("RCLONE_GDRIVE_CONF", "GDRIVE_CONF", "RCLONE_CONF_BASE64"),
    "secret/GOOGLE_DRIVE": ("RCLONE_GDRIVE_CONF", "GDRIVE_CONF", "RCLONE_CONF_BASE64"),
    "secret/GDRIVE": ("RCLONE_GDRIVE_CONF", "GDRIVE_CONF", "RCLONE_CONF_BASE64"),
}
REQUIRED_ENV = ("RCLONE_GDRIVE_CONF",)


class McpError(RuntimeError):
    pass


def token_from_env_file() -> str | None:
    for env_path in (os.environ.get("HERMES_ENV_PATH"), str(Path.home() / ".hermes" / ".env")):
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
    data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
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
                "clientInfo": {"name": "callnotes-cron", "version": "1"},
            },
        },
    )
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


def read_secret(url: str, token: str, session_id: str | None, path: str) -> dict[str, Any] | None:
    try:
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
    except McpError:
        return None
    content = response.get("result", {}).get("content", [])
    if not content:
        return None
    text = content[0].get("text", "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def collect_env(url: str, token: str) -> tuple[dict[str, str], dict[str, str]]:
    session_id = open_session(url, token)
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for path, candidate_keys in SECRET_CANDIDATES.items():
        data = read_secret(url, token, session_id, path)
        if not data:
            continue
        for key in candidate_keys:
            if data.get(key):
                values["RCLONE_GDRIVE_CONF"] = str(data[key])
                sources["RCLONE_GDRIVE_CONF"] = f"{path}:{key}"
                return values, sources
    return values, sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit callnotes automation env vars from Vault MCP")
    parser.add_argument("--mcp-url", default=os.environ.get("VAULT_MCP_URL", DEFAULT_MCP_URL))
    parser.add_argument("--check", action="store_true", help="print presence only; never print secret values")
    args = parser.parse_args()

    token = os.environ.get("VAULT_MCP_TOKEN") or token_from_env_file()
    if not token:
        print("ERROR: VAULT_MCP_TOKEN not found in environment or ~/.hermes/.env", file=sys.stderr)
        return 1

    try:
        env, sources = collect_env(args.mcp_url, token)
    except McpError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if args.check:
        for name in REQUIRED_ENV:
            source = sources.get(name, "missing")
            print(f"{name}: {'set' if env.get(name) else 'missing'} ({source})")
        if missing:
            print("ERROR: missing required callnotes secrets", file=sys.stderr)
            return 1
        return 0

    if missing:
        print(f"ERROR: missing required callnotes secrets: {', '.join(missing)}", file=sys.stderr)
        return 1
    for key, value in env.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
