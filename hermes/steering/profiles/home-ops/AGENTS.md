# home-ops profile workspace

This workspace belongs to the `home-ops` Hermes profile.

Use `/Users/sva/Documents/Repos/Github/home-ops` as the source of truth for durable Hermes/home-ops automation, profile steering, and local ops scripts.

Cron/automation scripts should live in `home-ops/hermes/scripts/` unless a more specific repo owns them. Keep generated reports/logs outside git or under ignored paths.

The former UniFi stack and its Hermes MCP/client-control helpers are retired. Current home-network work uses the Netgear PR60X router, MS510TXUP switch, and Ruckus R770 AP; do not recreate or call UniFi tooling.
