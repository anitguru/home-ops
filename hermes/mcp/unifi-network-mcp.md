# UniFi Network MCP access

Implementation plan recorded before live config changes for kanban task `t_b4b413b1`.

## Goal

Give Hermes agents safe MCP access to the local UniFi Network application on the gateway/router at `https://10.0.0.1`, using the existing `secret/UNIFI` HashiCorp Vault entry and without committing router credentials to git.

## Safety posture

- Start read-only. Expose inventory/inspection tools only: sites, devices, device stats, clients, networks, DNS policies, and a constrained generic GET helper.
- Do not expose mutation endpoints such as adopt/remove device, restart/power-cycle device or port, create/update/delete network, WiFi, firewall, ACL, DNS policy, or voucher operations in the first pass.
- Resolve credentials at runtime from Vault MCP via `VAULT_MCP_TOKEN`, or from explicit `UNIFI_API_KEY` / `UNIFI_BASE_URL` env vars if a caller provides them.
- Never log or print the UniFi API key. Smoke tests report endpoint status/counts only.

## Runtime design

- Stdio MCP server: `hermes/scripts/unifi_mcp.py`
- Hermes profile config entry: `mcp_servers.unifi-network`
- Default Network API prefix: `/proxy/network`, so MCP calls reach paths like `/proxy/network/integration/v1/sites`.
- Secret source: `secret/UNIFI` with keys `BASE_URL` and `API_KEY`.

## Verification steps

1. Parse/compile the Python server.
2. Run `unifi_mcp.py --check` to verify credentials can be resolved and `/integration/v1/sites` is reachable, without printing secret values.
3. Run `unifi_mcp.py --inventory --inventory-output <scratch-or-report-path>` to collect a read-only sites/devices/clients/networks/DNS summary. Keep generated inventory reports out of git unless a task explicitly asks to commit a snapshot.
4. Parse Hermes profile `config.yaml` to verify the MCP server entry is valid YAML.
5. Restart Hermes sessions/gateway before expecting MCP tools to appear; MCP tools are discovered only at agent startup.

## Exposed MCP tools

- `list_sites`
- `list_devices`
- `get_device`
- `get_device_statistics`
- `list_clients`
- `list_networks`
- `list_dns_policies`
- `unifi_get` for constrained read-only `integration/v1/...` paths
