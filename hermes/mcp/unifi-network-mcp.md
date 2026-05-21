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
- Secret source: `secret/UNIFI` with keys `BASE_URL` and `API_KEY`; confirmed block/unblock source-context verification uses Vault-backed `SOURCE_CONTEXT_KEY` when present, otherwise a local HMAC key derived from the Vault `API_KEY`.

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

## Ad hoc Everett computer block/unblock flow

The mutation path is intentionally not exposed through the read-only MCP server. Use
`scripts/unifi_ops.py` as a narrow deterministic helper for the pinned household
alias `Everett computer` only.

1. User asks from an authorized source: VanFam Telegram group/channel, SVA DM,
   AnITGuru DM, or a local SVA operator session.
2. Hermes runs read-only preflight, for example:
   `python scripts/unifi_ops.py block everett computer`
3. Hermes reports the resolved target (MAC `1c:f6:4c:3a:e8:13`, fixed IP
   `10.0.0.182`, DNS `everettmacmini.transformers.lan`), current UniFi client
   state, and exact phrase `confirm block Everett computer` (or `confirm unblock
   Everett computer`).
4. Only after the user replies with that exact phrase, the trusted gateway/wrapper
   supplies a short-lived HMAC `--source-context` token for the verified source and
   Hermes runs:
   `python scripts/unifi_ops.py block everett computer --confirm --request-source vanfam-telegram --source-context "$SIGNED_CONTEXT" --confirmation "confirm block Everett computer"`
   or the corresponding `unblock` command. The helper does not trust caller-set
   environment variables as proof of Telegram/DM origin.
5. The script uses the pinned household site ID
   `88f7af54-98f8-306a-a1c7-c9349722b1f6`, posts one official client action to
   `/integration/v1/sites/{site_id}/clients/{client_id}/actions`, and then reads
   the client again to verify the access state changed. Already-in-requested-state
   is idempotent and does not post.

Failure modes are fail-closed: ambiguous/incomplete alias, missing client,
unrecognized blocked state, missing/wrong confirmation phrase, missing/untrusted
source, missing/invalid/expired/mismatched signed source context on confirmed
mutation, API errors, and failed post-mutation verification all exit non-zero
before reporting success. Secrets are loaded from env or Vault MCP `secret/UNIFI`
and are never printed.
