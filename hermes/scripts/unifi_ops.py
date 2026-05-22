#!/usr/bin/env python3
"""Deterministic UniFi client block/unblock helper for pinned household devices.

Safe flow:
1. Run without --confirm for read-only preflight.
2. Show the exact confirmation phrase from the preflight output to the user.
3. Only after the user provides that exact phrase, run the same command with
   --confirm. The script then executes one narrow client action and verifies the
   device state afterward.

Credentials are resolved in this order:
1. UNIFI_API_KEY / UNIFI_BASE_URL environment variables.
2. HashiCorp Vault via the Vault MCP HTTP endpoint, reading secret/UNIFI.

No secrets are printed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MCP_URL = "https://vault-mcp.anit.guru/mcp"
DEFAULT_BASE_URL = "https://10.0.0.1"
DEFAULT_NETWORK_PREFIX = "/proxy/network"
DEFAULT_VAULT_SECRET_PATH = "secret/UNIFI"
DEFAULT_SITE_ID = "88f7af54-98f8-306a-a1c7-c9349722b1f6"

BLOCK_ACTION = "BLOCK"
UNBLOCK_ACTION = "UNBLOCK"

ALLOWED_REQUEST_SOURCES = {
    "local-sva",
    "sva-dm",
    "anitguru-dm",
    "vanfam-telegram",
    "vanfam-channel",
}


class UniFiOpsError(RuntimeError):
    """Base class for safe user-facing failures."""


class ConfigError(UniFiOpsError):
    pass


class McpVaultError(UniFiOpsError):
    pass


class AliasError(UniFiOpsError):
    pass


class DeviceLookupError(UniFiOpsError):
    pass


class BlockStateError(UniFiOpsError):
    pass


class PermissionDeniedError(UniFiOpsError):
    pass


class SourceContextError(PermissionDeniedError):
    pass


class ConfirmationError(UniFiOpsError):
    pass


class MutationVerificationError(UniFiOpsError):
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


@dataclass(frozen=True)
class InventoryTarget:
    canonical_alias: str
    aliases: tuple[str, ...]
    mac_address: str
    fixed_ip: str
    local_dns: str
    group_context: str
    connectivity: str

    def confirmation_phrase(self, action: str) -> str:
        return f"confirm {action} {self.canonical_alias}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "canonical_alias": self.canonical_alias,
            "mac_address": self.mac_address,
            "fixed_ip": self.fixed_ip,
            "local_dns": self.local_dns,
            "group_context": self.group_context,
            "connectivity": self.connectivity,
        }


PINNED_TARGETS: tuple[InventoryTarget, ...] = (
    InventoryTarget(
        canonical_alias="Everett computer",
        aliases=(
            "everett computer",
            "everetts computer",
            "everett's computer",
            "everett mac mini",
            "everetts mac mini",
            "everett's mac mini",
            "everetts-mac-mini",
            "everettmacmini.transformers.lan",
            "10.0.0.182",
            "1c:f6:4c:3a:e8:13",
        ),
        mac_address="1c:f6:4c:3a:e8:13",
        fixed_ip="10.0.0.182",
        local_dns="everettmacmini.transformers.lan",
        group_context="Everett's Stuff",
        connectivity="Wi-Fi only",
    ),
)


class UniFiApiLike(Protocol):
    def pick_site_id(self, preferred: str | None = None) -> str: ...

    def find_clients(self, site_id: str, target: InventoryTarget) -> list[dict[str, Any]]: ...

    def get_client(self, site_id: str, client_id: str) -> dict[str, Any]: ...

    def execute_client_action(self, site_id: str, client_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def normalize_prefix(prefix: str) -> str:
    prefix = (prefix or DEFAULT_NETWORK_PREFIX).strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")


def normalize_alias(text_or_tokens: str | list[str] | tuple[str, ...]) -> str:
    if isinstance(text_or_tokens, str):
        text = text_or_tokens
    else:
        text = " ".join(text_or_tokens)
    text = text.strip().lower().replace("’", "'")
    text = re.sub(r"\b's\b", "s", text)
    text = re.sub(r"[^a-z0-9:.\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_target(alias_tokens: list[str] | tuple[str, ...] | str) -> InventoryTarget:
    wanted = normalize_alias(alias_tokens)
    exact_matches = [target for target in PINNED_TARGETS if wanted in {normalize_alias(alias) for alias in target.aliases}]
    if len(exact_matches) == 1:
        return exact_matches[0]
    partial_matches = [
        target
        for target in PINNED_TARGETS
        if wanted and any(wanted in normalize_alias(alias).split() for alias in target.aliases)
    ]
    if partial_matches:
        names = ", ".join(target.canonical_alias for target in partial_matches)
        raise AliasError(f"ambiguous or incomplete alias '{wanted}'; use a full pinned alias such as: {names}")
    known = ", ".join(target.canonical_alias for target in PINNED_TARGETS)
    raise AliasError(f"unknown device alias '{wanted}'; known pinned targets: {known}")


def token_from_env_file() -> str | None:
    candidates = [os.environ.get("HERMES_ENV_PATH")]
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidates.append(str(Path(hermes_home).expanduser() / ".env"))
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
                "clientInfo": {"name": "unifi-ops", "version": "1"},
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
        secret = read_vault_secret(
            os.environ.get("VAULT_MCP_URL", DEFAULT_MCP_URL),
            token,
            os.environ.get("UNIFI_VAULT_SECRET_PATH", DEFAULT_VAULT_SECRET_PATH),
        )
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


def load_source_context_key() -> str:
    """Load the source-context verification key from Vault only.

    Deliberately do not accept a caller-controlled environment override here: a
    confirmed mutation must be authorized by a trusted wrapper/gateway that knows
    the same Vault-backed key, not by a user shell setting arbitrary env vars.
    """
    token = os.environ.get("VAULT_MCP_TOKEN") or token_from_env_file()
    if not token:
        raise ConfigError("VAULT_MCP_TOKEN was not found for UniFi source-context verification")
    secret = read_vault_secret(
        os.environ.get("VAULT_MCP_URL", DEFAULT_MCP_URL),
        token,
        os.environ.get("UNIFI_VAULT_SECRET_PATH", DEFAULT_VAULT_SECRET_PATH),
    )
    key = str(secret.get("SOURCE_CONTEXT_KEY") or secret.get("UNIFI_OPS_SOURCE_CONTEXT_KEY") or "")
    if key:
        return key
    api_key = str(secret.get("API_KEY") or "")
    if api_key:
        return hmac.new(api_key.encode(), b"unifi_ops_source_context_v1", hashlib.sha256).hexdigest()
    raise ConfigError("secret/UNIFI is missing SOURCE_CONTEXT_KEY and API_KEY for confirmed UniFi mutations")


def ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    if verify_tls:
        return None
    return ssl._create_unverified_context()  # noqa: SLF001 - local UniFi gateway uses a self-signed cert.


def safe_query(params: dict[str, Any | None]) -> str:
    clean = {key: value for key, value in params.items() if value is not None and value != ""}
    return urllib.parse.urlencode(clean)


class UniFiApi:
    def __init__(self, cfg: UniFiConfig | None = None):
        self.cfg = cfg or load_config()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, Any | None] | None = None) -> dict[str, Any]:
        path = "/" + path.lstrip("/")
        if not path.startswith("/integration/v1/"):
            raise ValueError("Only /integration/v1/... paths are allowed")
        qs = safe_query(query or {})
        url = self.cfg.api_base + path + (f"?{qs}" if qs else "")
        data = None if body is None else json.dumps(body).encode()
        headers = {"X-API-KEY": self.cfg.api_key, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl_context(self.cfg.verify_tls)) as response:
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
            raise UniFiOpsError(f"UniFi API HTTP {exc.code} for {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise UniFiOpsError(f"UniFi API request failed for {method} {path}: {exc}") from exc

    def pick_site_id(self, preferred: str | None = None) -> str:
        # Deterministic household default: do not silently pick the first site in
        # multi-site controllers. Operators may still override explicitly.
        return preferred or DEFAULT_SITE_ID

    def find_clients(self, site_id: str, target: InventoryTarget) -> list[dict[str, Any]]:
        # The official Integration API documents macAddress and ipAddress as filterable for clients.
        # Name is intentionally not used here: some Network versions reject it as an invalid filter.
        filters = [
            f"macAddress.eq('{target.mac_address}')",
            f"ipAddress.eq('{target.fixed_ip}')",
        ]
        matches: dict[str, dict[str, Any]] = {}
        for filter_value in filters:
            payload = self.request(
                "GET",
                f"/integration/v1/sites/{site_id}/clients",
                query={"limit": 25, "filter": filter_value},
            )
            data = payload.get("data")
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                client_id = str(item.get("id") or item.get("macAddress") or "")
                if client_id:
                    matches[client_id] = item
        exact = []
        for item in matches.values():
            mac = str(item.get("macAddress") or "").lower()
            ip = str(item.get("ipAddress") or "")
            if mac == target.mac_address or ip == target.fixed_ip:
                exact.append(item)
        return exact

    def get_client(self, site_id: str, client_id: str) -> dict[str, Any]:
        return self.request("GET", f"/integration/v1/sites/{site_id}/clients/{client_id}")

    def execute_client_action(self, site_id: str, client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/integration/v1/sites/{site_id}/clients/{client_id}/actions", body=payload)


def selected_client_fields(client: dict[str, Any]) -> dict[str, Any]:
    return {
        key: client[key]
        for key in ("id", "name", "macAddress", "ipAddress", "type", "uplinkDeviceId", "connectedAt", "access")
        if key in client and client[key] not in (None, "")
    }


def extract_blocked(client: dict[str, Any]) -> bool | None:
    for key in ("blocked", "isBlocked", "networkBlocked"):
        value = client.get(key)
        if isinstance(value, bool):
            return value
    access = client.get("access")
    if isinstance(access, dict):
        access_type = str(access.get("type") or "").upper()
        if access_type in {"BLOCK", "BLOCKED", "DENY", "DENIED"}:
            return True
        if access_type in {"DEFAULT", "ALLOW", "ALLOWED"}:
            return False
    access_type = str(client.get("accessType") or client.get("access_type") or "").upper()
    if access_type in {"BLOCK", "BLOCKED", "DENY", "DENIED"}:
        return True
    if access_type in {"DEFAULT", "ALLOW", "ALLOWED"}:
        return False
    return None


def normalize_request_source(request_source: str) -> str:
    return normalize_alias(request_source).replace(" ", "-")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def make_source_context(
    *,
    source: str,
    action: str,
    target: InventoryTarget,
    confirmation: str,
    key: str,
    site_id: str = DEFAULT_SITE_ID,
    expires_at: int | None = None,
    issued_at: int | None = None,
) -> str:
    """Create a signed source-context token for a trusted gateway/wrapper.

    This is intentionally HMAC-signed so the mutation helper does not trust a
    caller-settable environment variable or free-form CLI source claim. The key
    must come from trusted local configuration, not from the user request.
    """
    if not key:
        raise SourceContextError("source context signing key is missing")
    now = int(time.time()) if issued_at is None else int(issued_at)
    payload = {
        "v": 1,
        "scope": "unifi_ops_source_context",
        "source": normalize_request_source(source),
        "action": action.lower().strip(),
        "target": target.canonical_alias,
        "site_id": site_id,
        "confirmation": confirmation,
        "iat": now,
        "exp": int(expires_at) if expires_at is not None else now + 300,
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(key.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"v1.{_b64url_encode(payload_bytes)}.{signature}"


def verify_source_context(
    source_context: str | None,
    *,
    key: str | None,
    request_source: str,
    action: str,
    target: InventoryTarget,
    confirmation: str,
    site_id: str,
    now: int | None = None,
) -> None:
    if not source_context:
        raise SourceContextError("confirmed UniFi mutations require --source-context from a trusted wrapper/gateway")
    if not key:
        raise SourceContextError("confirmed UniFi mutations require a trusted source-context signing key")
    try:
        version, encoded_payload, signature = source_context.split(".", 2)
    except ValueError as exc:
        raise SourceContextError("source context is malformed") from exc
    if version != "v1":
        raise SourceContextError("source context has an unsupported version")
    payload_bytes = _b64url_decode(encoded_payload)
    expected_signature = hmac.new(key.encode(), payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise SourceContextError("source context signature is invalid")
    try:
        payload = json.loads(payload_bytes.decode())
    except json.JSONDecodeError as exc:
        raise SourceContextError("source context payload is not JSON") from exc
    expected = {
        "v": 1,
        "scope": "unifi_ops_source_context",
        "source": normalize_request_source(request_source),
        "action": action.lower().strip(),
        "target": target.canonical_alias,
        "site_id": site_id,
        "confirmation": confirmation,
    }
    for key_name, expected_value in expected.items():
        if payload.get(key_name) != expected_value:
            raise SourceContextError(f"source context {key_name} does not match this confirmed operation")
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise SourceContextError("source context is missing an integer expiration")
    if (int(time.time()) if now is None else int(now)) > expires_at:
        raise SourceContextError("source context has expired")


def ensure_authorized_source(
    request_source: str | None,
    *,
    action: str,
    target: InventoryTarget,
    confirmation: str | None,
    site_id: str,
    source_context: str | None = None,
    source_context_key: str | None = None,
) -> None:
    if not request_source:
        raise PermissionDeniedError(
            "confirmed UniFi mutations require --request-source; allowed sources: "
            + ", ".join(sorted(ALLOWED_REQUEST_SOURCES))
        )
    normalized = normalize_request_source(request_source)
    if normalized not in ALLOWED_REQUEST_SOURCES:
        raise PermissionDeniedError(
            f"request source '{request_source}' is not authorized for UniFi mutations; allowed sources: "
            + ", ".join(sorted(ALLOWED_REQUEST_SOURCES))
        )
    if confirmation is None:
        raise ConfirmationError(f"confirmation phrase must exactly match: {target.confirmation_phrase(action)}")
    verify_source_context(
        source_context,
        key=source_context_key,
        request_source=normalized,
        action=action,
        target=target,
        confirmation=confirmation,
        site_id=site_id,
    )


def ensure_confirmation_phrase(target: InventoryTarget, action: str, confirmation: str | None) -> None:
    expected = target.confirmation_phrase(action)
    if confirmation != expected:
        raise ConfirmationError(f"confirmation phrase must exactly match: {expected}")


def matching_client(clients: list[dict[str, Any]], target: InventoryTarget) -> dict[str, Any]:
    if not clients:
        raise DeviceLookupError(
            f"pinned target {target.canonical_alias} not found in UniFi clients "
            f"(expected MAC {target.mac_address}, IP {target.fixed_ip})"
        )
    exact = [
        client
        for client in clients
        if str(client.get("macAddress") or "").lower() == target.mac_address
        or str(client.get("ipAddress") or "") == target.fixed_ip
    ]
    if len(exact) != 1:
        raise DeviceLookupError(
            f"expected exactly one UniFi client for {target.canonical_alias}; found {len(exact)} exact matches"
        )
    return exact[0]


def run_operation(
    action: str,
    alias_tokens: list[str] | tuple[str, ...] | str,
    *,
    api: UniFiApiLike | None = None,
    confirm: bool = False,
    site_id: str | None = None,
    request_source: str | None = None,
    source_context: str | None = None,
    source_context_key: str | None = None,
    confirmation: str | None = None,
) -> dict[str, Any]:
    action = action.lower().strip()
    if action not in {"block", "unblock"}:
        raise ValueError("action must be 'block' or 'unblock'")
    target = resolve_target(alias_tokens)
    operation_site_id = site_id or DEFAULT_SITE_ID
    if operation_site_id != DEFAULT_SITE_ID:
        raise PermissionDeniedError(
            f"{target.canonical_alias} operations are pinned to UniFi site {DEFAULT_SITE_ID}; "
            "site overrides are not allowed for block/unblock"
        )
    if confirm:
        ensure_confirmation_phrase(target, action, confirmation)
        ensure_authorized_source(
            request_source,
            action=action,
            target=target,
            confirmation=confirmation,
            site_id=operation_site_id,
            source_context=source_context,
            source_context_key=source_context_key,
        )
    api = api or UniFiApi()
    picked_site_id = api.pick_site_id(operation_site_id)
    client_summary = matching_client(api.find_clients(picked_site_id, target), target)
    client_id = str(client_summary.get("id") or "")
    if not client_id:
        raise DeviceLookupError(f"UniFi client for {target.canonical_alias} did not include an id")
    client_detail = api.get_client(picked_site_id, client_id)
    current_blocked = extract_blocked(client_detail)
    if current_blocked is None:
        raise BlockStateError(
            f"UniFi client state for {target.canonical_alias} did not include a recognized blocked/default access field"
        )
    desired_blocked = action == "block"
    result: dict[str, Any] = {
        "action": action,
        "target": target.public_dict(),
        "site_id": picked_site_id,
        "client": selected_client_fields(client_detail),
        "current_blocked": current_blocked,
        "desired_blocked": desired_blocked,
        "confirmation_phrase": target.confirmation_phrase(action),
        "requires_confirmation": False,
        "mutated": False,
        "idempotent": False,
        "verified": False,
        "verified_blocked": None,
    }
    if current_blocked == desired_blocked:
        result.update(
            {
                "idempotent": True,
                "verified": True,
                "verified_blocked": current_blocked,
                "message": f"{target.canonical_alias} is already {'blocked' if desired_blocked else 'unblocked'}.",
            }
        )
        return result
    if not confirm:
        result.update(
            {
                "requires_confirmation": True,
                "message": "Preflight only; no UniFi mutation performed. Re-run with --confirm only after exact user confirmation.",
            }
        )
        return result
    payload = {"action": BLOCK_ACTION if desired_blocked else UNBLOCK_ACTION}
    result["mutation"] = {"endpoint": f"/integration/v1/sites/{picked_site_id}/clients/{client_id}/actions", "payload": payload}
    api.execute_client_action(picked_site_id, client_id, payload)
    verified_detail = api.get_client(picked_site_id, client_id)
    verified_blocked = extract_blocked(verified_detail)
    result["mutated"] = True
    result["verified_blocked"] = verified_blocked
    result["verified_client"] = selected_client_fields(verified_detail)
    result["verified"] = verified_blocked == desired_blocked
    if not result["verified"]:
        raise MutationVerificationError(
            f"UniFi action returned but verification did not show {target.canonical_alias} "
            f"as {'blocked' if desired_blocked else 'unblocked'}"
        )
    result["message"] = f"Verified {target.canonical_alias} is now {'blocked' if desired_blocked else 'unblocked'}."
    return result


def run_blocked(alias_tokens: list[str] | None, *, api: UniFiApiLike | None = None, site_id: str | None = None) -> dict[str, Any]:
    targets = [resolve_target(alias_tokens)] if alias_tokens else list(PINNED_TARGETS)
    api = api or UniFiApi()
    picked_site_id = api.pick_site_id(site_id)
    devices: list[dict[str, Any]] = []
    for target in targets:
        client_summary = matching_client(api.find_clients(picked_site_id, target), target)
        client_id = str(client_summary.get("id") or "")
        client_detail = api.get_client(picked_site_id, client_id)
        devices.append(
            {
                "target": target.public_dict(),
                "client": selected_client_fields(client_detail),
                "blocked": extract_blocked(client_detail),
            }
        )
    return {"site_id": picked_site_id, "devices": devices}


def render_result(result: dict[str, Any]) -> str:
    lines = []
    target = result.get("target", {})
    if target:
        lines.append(f"Target: {target.get('canonical_alias')} ({target.get('mac_address')} / {target.get('fixed_ip')})")
        lines.append(f"DNS/group: {target.get('local_dns')} / {target.get('group_context')}")
    if "client" in result:
        client = result["client"]
        lines.append(
            "UniFi client: "
            f"{client.get('name', 'unknown')} id={client.get('id', 'unknown')} "
            f"ip={client.get('ipAddress', 'unknown')} mac={client.get('macAddress', 'unknown')}"
        )
    if "current_blocked" in result:
        lines.append(f"Current blocked: {result.get('current_blocked')}")
    if result.get("requires_confirmation"):
        lines.append("No mutation performed.")
        lines.append(f"Exact confirmation phrase: {result.get('confirmation_phrase')}")
    elif result.get("idempotent"):
        lines.append("No mutation performed: already in requested state.")
    elif result.get("mutated"):
        lines.append(f"Mutation performed and verified: {result.get('verified')}")
        lines.append(f"Verified blocked: {result.get('verified_blocked')}")
    if result.get("message"):
        lines.append(str(result["message"]))
    return "\n".join(lines)


def render_blocked(result: dict[str, Any]) -> str:
    lines = [f"Site: {result.get('site_id')}"]
    for item in result.get("devices", []):
        target = item.get("target", {})
        client = item.get("client", {})
        lines.append(
            f"{target.get('canonical_alias')}: blocked={item.get('blocked')} "
            f"name={client.get('name', 'unknown')} ip={client.get('ipAddress', 'unknown')} "
            f"mac={client.get('macAddress', target.get('mac_address', 'unknown'))}"
        )
    return "\n".join(lines)


def audit_log_path() -> Path:
    configured = os.environ.get("UNIFI_OPS_AUDIT_LOG")
    if configured:
        return Path(configured).expanduser()
    return Path("/Users/sva/Documents/Repos/Github/home-ops/hermes/logs/unifi-ops.jsonl")


def append_audit_event(event: dict[str, Any]) -> None:
    """Append a sanitized UniFi ops audit event.

    The audit log is intentionally local runtime state under a gitignored path.
    It records aliases/MAC/IP/state transitions and failures, but never records
    API keys, Vault tokens, signed source-context tokens, or raw secret values.
    """
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_event = {
        "ts": int(time.time()),
        "tool": "unifi_ops.py",
        "schema": "unifi_ops_audit_v1",
        **event,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_event, sort_keys=True, separators=(",", ":")) + "\n")


def audit_success(command: str, args: argparse.Namespace, result: dict[str, Any]) -> None:
    event: dict[str, Any] = {
        "command": command,
        "status": "success",
        "site_id": result.get("site_id"),
    }
    if command in {"block", "unblock"}:
        event.update(
            {
                "action": command,
                "alias": " ".join(getattr(args, "alias", []) or []),
                "target": result.get("target"),
                "request_source": normalize_request_source(args.request_source) if args.request_source else None,
                "confirm_requested": bool(args.confirm),
                "requires_confirmation": result.get("requires_confirmation"),
                "current_blocked": result.get("current_blocked"),
                "desired_blocked": result.get("desired_blocked"),
                "mutated": result.get("mutated"),
                "idempotent": result.get("idempotent"),
                "verified": result.get("verified"),
                "verified_blocked": result.get("verified_blocked"),
            }
        )
    elif command == "blocked":
        event["devices"] = [
            {
                "target": item.get("target"),
                "client": selected_client_fields(item.get("client", {})),
                "blocked": item.get("blocked"),
            }
            for item in result.get("devices", [])
        ]
    append_audit_event(event)


def audit_failure(command: str | None, args: argparse.Namespace, exc: Exception) -> None:
    event: dict[str, Any] = {
        "command": command,
        "status": "failure",
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    if command in {"block", "unblock"}:
        event.update(
            {
                "action": command,
                "alias": " ".join(getattr(args, "alias", []) or []),
                "request_source": normalize_request_source(args.request_source) if getattr(args, "request_source", None) else None,
                "confirm_requested": bool(getattr(args, "confirm", False)),
            }
        )
    append_audit_event(event)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="render machine-readable JSON")
    parser.add_argument("--site-id", default=argparse.SUPPRESS, help="explicit UniFi site UUID; defaults to pinned household site")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic UniFi block/unblock helper for pinned local inventory")
    add_common_args(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("block", "unblock"):
        cmd = sub.add_parser(name, help=f"preflight or {name} a pinned device")
        add_common_args(cmd)
        cmd.add_argument("alias", nargs="+", help="pinned device alias, e.g. everett computer")
        cmd.add_argument("--confirm", action="store_true", help="perform the mutation after exact user confirmation")
        cmd.add_argument("--confirmation", help="exact phrase from preflight, e.g. 'confirm block Everett computer'")
        cmd.add_argument(
            "--request-source",
            help="required source gate when --confirm is used, e.g. vanfam-telegram or sva-dm",
        )
        cmd.add_argument(
            "--source-context",
            help="HMAC-signed trusted source context from the gateway/wrapper; required when --confirm is used",
        )
    blocked = sub.add_parser("blocked", help="read and report blocked state for pinned targets")
    add_common_args(blocked)
    blocked.add_argument("alias", nargs="*", help="optional pinned alias; defaults to all pinned targets")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"block", "unblock"}:
            result = run_operation(
                args.command,
                args.alias,
                confirm=args.confirm,
                site_id=getattr(args, "site_id", None),
                request_source=args.request_source,
                source_context=args.source_context,
                source_context_key=load_source_context_key() if args.confirm and args.source_context else None,
                confirmation=args.confirmation,
            )
            audit_success(args.command, args, result)
            print(json.dumps(result, indent=2, sort_keys=True) if getattr(args, "json", False) else render_result(result))
            return 0
        if args.command == "blocked":
            result = run_blocked(args.alias or None, site_id=getattr(args, "site_id", None))
            audit_success(args.command, args, result)
            print(json.dumps(result, indent=2, sort_keys=True) if getattr(args, "json", False) else render_blocked(result))
            return 0
    except UniFiOpsError as exc:
        audit_failure(getattr(args, "command", None), args, exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unsupported command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
