#!/usr/bin/env python3
"""Read-only MCP server for the local UniFi Network API.

Credentials are resolved in this order:
1. UNIFI_API_KEY / UNIFI_BASE_URL environment variables.
2. HashiCorp Vault via the Vault MCP HTTP endpoint, reading secret/UNIFI.

The server intentionally exposes only GET/read tools. Do not add mutating UniFi
operations here without updating hermes/mcp/unifi-network-mcp.md first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

DEFAULT_MCP_URL = "https://vault-mcp.anit.guru/mcp"
DEFAULT_BASE_URL = "https://10.0.0.1"
DEFAULT_NETWORK_PREFIX = "/proxy/network"

mcp = FastMCP("unifi-network")


class ConfigError(RuntimeError):
    pass


class McpVaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class UniFiConfig:
    base_url: str
    api_key: str
    network_prefix: str = DEFAULT_NETWORK_PREFIX
    verify_tls: bool = False

    @property
    def api_base(self) -> str:
        return self.base_url.rstrip("/") + normalize_prefix(self.network_prefix)


def normalize_prefix(prefix: str) -> str:
    prefix = (prefix or DEFAULT_NETWORK_PREFIX).strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")


def token_from_env_file() -> str | None:
    candidates = [os.environ.get("HERMES_ENV_PATH")]
    hermes_profile = os.environ.get("HERMES_PROFILE")
    if hermes_profile:
        candidates.append(str(Path.home().parent / hermes_profile / ".env"))
    candidates.extend(
        [
            os.path.expanduser("~/.hermes/profiles/home-ops/.env"),
            os.path.expanduser("~/.hermes/.env"),
        ]
    )
    for env_path in candidates:
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
        raise McpVaultError(f"Vault MCP HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise McpVaultError(f"Vault MCP request failed: {exc}") from exc
    data = parse_sse_json(raw)
    if data.get("error"):
        raise McpVaultError(json.dumps(data["error"], sort_keys=True))
    return data, new_session


def open_vault_session(url: str, token: str) -> str | None:
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
                "clientInfo": {"name": "unifi-network-mcp", "version": "1"},
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


def read_vault_secret(url: str, token: str, path: str) -> dict[str, Any]:
    session_id = open_vault_session(url, token)
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
        raise McpVaultError(f"empty Vault MCP response for {path}")
    text = content[0].get("text", "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpVaultError(f"non-JSON Vault secret response for {path}") from exc
    if not isinstance(data, dict):
        raise McpVaultError(f"unexpected Vault secret shape for {path}")
    return data


def load_config() -> UniFiConfig:
    base_url = os.environ.get("UNIFI_BASE_URL") or DEFAULT_BASE_URL
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        token = os.environ.get("VAULT_MCP_TOKEN") or token_from_env_file()
        if not token:
            raise ConfigError("UNIFI_API_KEY is unset and VAULT_MCP_TOKEN was not found")
        secret = read_vault_secret(os.environ.get("VAULT_MCP_URL", DEFAULT_MCP_URL), token, "secret/UNIFI")
        base_url = str(secret.get("BASE_URL") or base_url)
        api_key = str(secret.get("API_KEY") or "")
    if not api_key:
        raise ConfigError("UniFi API key is missing")
    return UniFiConfig(
        base_url=base_url,
        api_key=api_key,
        network_prefix=os.environ.get("UNIFI_NETWORK_PREFIX", DEFAULT_NETWORK_PREFIX),
        verify_tls=os.environ.get("UNIFI_VERIFY_TLS", "false").lower() in {"1", "true", "yes"},
    )


def ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    if verify_tls:
        return None
    return ssl._create_unverified_context()  # noqa: SLF001 - local UniFi gateway uses a self-signed cert.


def safe_query(params: dict[str, Any | None]) -> str:
    clean = {key: value for key, value in params.items() if value is not None and value != ""}
    return urllib.parse.urlencode(clean)


def unifi_get_path(path: str, query: dict[str, Any | None] | None = None) -> dict[str, Any]:
    cfg = load_config()
    path = "/" + path.lstrip("/")
    if not path.startswith("/integration/v1/"):
        raise ValueError("Only read-only /integration/v1/... paths are allowed")
    qs = safe_query(query or {})
    url = cfg.api_base + path + (f"?{qs}" if qs else "")
    request = urllib.request.Request(
        url,
        headers={"X-API-KEY": cfg.api_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context(cfg.verify_tls)) as response:
            raw = response.read().decode(errors="replace")
            if not raw:
                return {"status": response.status, "data": None}
            payload = json.loads(raw)
            if isinstance(payload, dict):
                payload.setdefault("status", response.status)
                return payload
            return {"status": response.status, "data": payload}
    except urllib.error.HTTPError as exc:
        detail = exc.read(800).decode(errors="replace")
        raise RuntimeError(f"UniFi API HTTP {exc.code} for {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"UniFi API request failed for {path}: {exc}") from exc


def pick_site_id(site_id: str | None) -> str:
    if site_id:
        return site_id
    sites = unifi_get_path("/integration/v1/sites", {"limit": 25})
    data = sites.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("No UniFi sites returned; provide site_id explicitly")
    first = data[0]
    if not isinstance(first, dict) or not first.get("id"):
        raise RuntimeError("UniFi sites response did not contain an id")
    return str(first["id"])


@mcp.tool()
def list_sites(limit: int = 25, offset: int = 0, filter: str | None = None) -> dict[str, Any]:
    """List local UniFi Network sites. Use a returned site id for site-scoped tools."""
    return unifi_get_path("/integration/v1/sites", {"limit": limit, "offset": offset, "filter": filter})


@mcp.tool()
def list_devices(site_id: str | None = None, limit: int = 100, offset: int = 0, filter: str | None = None) -> dict[str, Any]:
    """List adopted UniFi devices for a site. Defaults to the first local site."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/devices", {"limit": limit, "offset": offset, "filter": filter})


@mcp.tool()
def get_device(device_id: str, site_id: str | None = None) -> dict[str, Any]:
    """Get details for one adopted UniFi device."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/devices/{device_id}")


@mcp.tool()
def get_device_statistics(device_id: str, site_id: str | None = None) -> dict[str, Any]:
    """Get latest health/statistics for one adopted UniFi device."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/devices/{device_id}/statistics/latest")


@mcp.tool()
def list_clients(site_id: str | None = None, limit: int = 100, offset: int = 0, filter: str | None = None) -> dict[str, Any]:
    """List connected clients for a site. Defaults to the first local site."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/clients", {"limit": limit, "offset": offset, "filter": filter})


@mcp.tool()
def list_networks(site_id: str | None = None, limit: int = 100, offset: int = 0, filter: str | None = None) -> dict[str, Any]:
    """List VLAN/network configurations for a site."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/networks", {"limit": limit, "offset": offset, "filter": filter})


@mcp.tool()
def list_dns_policies(site_id: str | None = None, limit: int = 100, offset: int = 0, filter: str | None = None) -> dict[str, Any]:
    """List local DNS policies/records for a site."""
    sid = pick_site_id(site_id)
    return unifi_get_path(f"/integration/v1/sites/{sid}/dns/policies", {"limit": limit, "offset": offset, "filter": filter})


@mcp.tool()
def unifi_get(path: str, limit: int | None = None, offset: int | None = None, filter: str | None = None) -> dict[str, Any]:
    """Constrained read-only GET helper for /integration/v1/... API paths."""
    query: dict[str, Any | None] = {"limit": limit, "offset": offset, "filter": filter}
    return unifi_get_path(path, query)


def response_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def pick_fields(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item[field] for field in fields if field in item and item[field] not in (None, "")}


def collect_inventory(limit: int = 500) -> dict[str, Any]:
    """Collect a read-only UniFi inventory without exposing API credentials."""
    cfg = load_config()
    sites_payload = unifi_get_path("/integration/v1/sites", {"limit": limit})
    sites: list[dict[str, Any]] = []
    for site in response_data(sites_payload):
        site_id = str(site.get("id") or "")
        site_record: dict[str, Any] = {
            "site": pick_fields(site, ("id", "internalReference", "name")),
            "devices": [],
            "clients": [],
            "networks": [],
            "dns_policies": [],
            "counts": {},
        }
        if not site_id:
            sites.append(site_record)
            continue
        endpoints = {
            "devices": f"/integration/v1/sites/{site_id}/devices",
            "clients": f"/integration/v1/sites/{site_id}/clients",
            "networks": f"/integration/v1/sites/{site_id}/networks",
            "dns_policies": f"/integration/v1/sites/{site_id}/dns/policies",
        }
        field_sets = {
            "devices": ("id", "name", "model", "state", "ipAddress", "firmwareVersion", "firmwareUpdatable"),
            "clients": ("id", "name", "type", "ipAddress", "uplinkDeviceId", "connectedAt"),
            "networks": ("id", "name", "enabled", "vlanId", "management", "default"),
            "dns_policies": ("id", "type", "enabled", "domain", "ipv4Address", "ipv6Address", "targetDomain", "ttlSeconds"),
        }
        for key, endpoint in endpoints.items():
            payload = unifi_get_path(endpoint, {"limit": limit})
            items = [pick_fields(item, field_sets[key]) for item in response_data(payload)]
            site_record[key] = items
            site_record["counts"][key] = len(items)
        sites.append(site_record)
    return {
        "base_url": cfg.base_url.rstrip("/"),
        "network_prefix": cfg.network_prefix,
        "read_only": True,
        "sites": sites,
        "counts": {
            "sites": len(sites),
            "devices": sum(int(site.get("counts", {}).get("devices", 0)) for site in sites),
            "clients": sum(int(site.get("counts", {}).get("clients", 0)) for site in sites),
            "networks": sum(int(site.get("counts", {}).get("networks", 0)) for site in sites),
            "dns_policies": sum(int(site.get("counts", {}).get("dns_policies", 0)) for site in sites),
        },
    }


def render_inventory_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# UniFi read-only inventory summary",
        "",
        f"Base URL: `{inventory['base_url']}`",
        f"Network prefix: `{inventory['network_prefix']}`",
        "Mode: read-only GET inventory; no UniFi mutation endpoints are called.",
        "",
        "## Counts",
    ]
    counts = inventory.get("counts", {})
    for key in ("sites", "devices", "clients", "networks", "dns_policies"):
        lines.append(f"- {key.replace('_', ' ').title()}: {counts.get(key, 0)}")
    for site in inventory.get("sites", []):
        site_info = site.get("site", {})
        site_name = site_info.get("name") or site_info.get("id") or "unknown"
        lines.extend(["", f"## Site: {site_name}", ""])
        lines.append("### Networks / VLANs")
        for network in site.get("networks", []):
            vlan = network.get("vlanId", "untagged/default")
            enabled = network.get("enabled", "unknown")
            lines.append(f"- {network.get('name', network.get('id', 'unknown'))}: vlan={vlan}, enabled={enabled}")
        lines.append("")
        lines.append("### DNS policies / local DNS records")
        for record in site.get("dns_policies", []):
            target = record.get("ipv4Address") or record.get("ipv6Address") or record.get("targetDomain") or "unknown-target"
            lines.append(f"- {record.get('domain', record.get('id', 'unknown'))}: {record.get('type', 'record')} -> {target}")
        lines.append("")
        lines.append("### UniFi devices")
        for device in site.get("devices", []):
            lines.append(
                f"- {device.get('name', device.get('id', 'unknown'))}: "
                f"{device.get('model', 'unknown-model')}, {device.get('state', 'unknown-state')}, "
                f"ip={device.get('ipAddress', 'unknown')}"
            )
        lines.append("")
        lines.append("### Clients")
        client_counts: dict[str, int] = {}
        for client in site.get("clients", []):
            client_type = str(client.get("type") or "UNKNOWN")
            client_counts[client_type] = client_counts.get(client_type, 0) + 1
        if client_counts:
            for client_type, count in sorted(client_counts.items()):
                lines.append(f"- {client_type}: {count}")
        else:
            lines.append("- none reported")
    lines.append("")
    return "\n".join(lines)


def run_inventory(format_name: str, output_path: str | None, limit: int) -> int:
    try:
        inventory = collect_inventory(limit=limit)
    except Exception as exc:  # noqa: BLE001 - CLI should summarize any setup/API failure.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if format_name == "json":
        rendered = json.dumps(inventory, indent=2, sort_keys=True)
    else:
        rendered = render_inventory_markdown(inventory)
    if output_path:
        Path(output_path).expanduser().write_text(rendered + "\n")
        print(f"Wrote UniFi read-only inventory to {output_path}")
    else:
        print(rendered)
    return 0


def run_check() -> int:
    try:
        cfg = load_config()
        sites = unifi_get_path("/integration/v1/sites", {"limit": 25})
    except Exception as exc:  # noqa: BLE001 - check mode should summarize any setup failure.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    data = sites.get("data") if isinstance(sites, dict) else None
    count = len(data) if isinstance(data, list) else "unknown"
    print("UniFi MCP check: credentials resolved")
    print(f"UniFi MCP check: base_url={cfg.base_url.rstrip('/')} prefix={cfg.network_prefix}")
    print(f"UniFi MCP check: sites reachable count={count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only UniFi Network MCP server")
    parser.add_argument("--check", action="store_true", help="verify credentials and site listing without starting stdio MCP")
    parser.add_argument("--inventory", action="store_true", help="collect read-only sites/devices/clients/networks/DNS inventory")
    parser.add_argument("--inventory-format", choices=("markdown", "json"), default="markdown", help="inventory output format")
    parser.add_argument("--inventory-output", help="write inventory output to this path instead of stdout")
    parser.add_argument("--limit", type=int, default=500, help="per-endpoint inventory page size")
    args = parser.parse_args()
    if args.check:
        return run_check()
    if args.inventory:
        return run_inventory(args.inventory_format, args.inventory_output, args.limit)
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
