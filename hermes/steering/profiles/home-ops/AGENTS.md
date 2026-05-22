# home-ops profile workspace

This workspace belongs to the `home-ops` Hermes profile.

Use `/Users/sva/Documents/Repos/Github/home-ops` as the source of truth for durable Hermes/home-ops automation, profile steering, and local ops scripts.

Cron/automation scripts should live in `home-ops/hermes/scripts/` unless a more specific repo owns them. Keep generated reports/logs outside git or under ignored paths.

UniFi/network-control workflow now lives in this `home-ops` profile rather than a separate `unifi-ops` profile. Keep discovery in the read-only `unifi-network` MCP, and use `hermes/scripts/unifi_ops.py` only for deterministic confirmed client-control scaffolding with exact confirmation and audit logging.
