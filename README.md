# home-ops

Version-controlled operational runbooks, Hermes profile steering, and helper scripts for SVA's local/homelab automations.

## Hermes operations

- `hermes/scripts/` — repo-backed scripts and launcher wrappers used by Hermes cron jobs/profiles.
- `hermes/podcast/README.md` — canonical Guru's Tech Bytes daily podcast producer/publisher runbook.
- `hermes/wiki-freshness/` — deterministic wiki freshness audit implementation.
- `hermes/x-social/` — X/Twitter posting and engagement automation logic.
- `hermes/mcp/` — local MCP notes/configuration docs.

Runtime configs, logs, generated artifacts, caches, and secrets stay outside git unless a specific runbook says otherwise.
