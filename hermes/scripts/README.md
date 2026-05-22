# Hermes ops scripts

Version-controlled scripts used by Hermes profiles and cronjobs.

Runtime configs, reports, manifests, logs, generated podcast artifacts, and secrets should stay outside git unless explicitly documented otherwise.

## Runbooks

- `../podcast/README.md` — canonical Guru's Tech Bytes daily podcast producer/publisher runbook. The active production scripts now live under `../podcast/scripts/`; scheduled Hermes jobs must not call the retiring `/Users/sva/Documents/Repos/Gitea/automations` copies.

## Python helpers

- `hermes_llm.py` — shared subprocess bridge for Hermes one-shot LLM calls. It strips legacy direct-provider env vars and nested TUI/session env before launching `hermes chat -q`.
- `hn_topic_refresh_hermes.py` — optional Hacker News topic enrichment job. It fetches HN stories/comments, extracts canonical topics through Hermes one-shot profiles, and can dry-run or write rows compatible with the automations repo's `hntrendingtopics__hn_topics` table.
- `post_actions_cron.sh` / `engage_actions_cron.sh` — default-profile Hermes no-agent cron launchers for @anitdotguru X posting and engagement. These run the borrowed social automation logic now housed under `hermes/x-social/` and intentionally do not call Gitea Actions, runners, direct Claude/Anthropic APIs, or `git push`. Mutable post/cursor state is kept outside git at `${X_SOCIAL_STATE_DIR:-${HERMES_STATE_DIR:-$HOME/.local/state/home-ops}/x-social}` so successful cron runs do not dirty the checkout. Posting drafts may use Grok via the `xposting` one-shot profile, but only with `--toolsets terminal` so xAI's 200-tool request limit is not hit by the default Telegram profile's full tool surface.
- `weekly_x_growth_audit_cron.sh` — default-profile Hermes no-agent weekly audit for @anitdotguru X growth. It refreshes read-only post metrics, asks Grok through the same minimal-tool `xposting` profile for follower-growth feedback, appends the report to the Obsidian wiki page `40-wiki/queries/x-growth-feedback.md`, and deterministically tunes the X posting/engagement cron cadences unless `X_GROWTH_AUTOTUNE_CRONS=0`.
- `wiki_freshness_cron.sh` — default-profile Hermes no-agent cron launcher for the wiki source freshness audit now housed under `hermes/wiki-freshness/`. The active scheduled path is deterministic (`--dry-run --no-llm`) and intentionally avoids Gitea Actions, runners, Git push/writeback, and direct Claude/Anthropic APIs.
- `docs_wishlist_cron.sh` — default-profile Hermes no-agent cron launcher for the docs wishlist ingest now housed under `hermes/docs-wishlist/`. The active scheduled path writes docs pages by default (`--no-dry-run`, `RSS_INGEST_USE_LLM=0`) and intentionally avoids Gitea Actions, runners, Git push/writeback, Obsidian MCP, and direct Claude/Anthropic APIs by default. Pass `--dry-run` manually for audits.
- `share-latest-podcast-audio.sh` — no-agent cron/watchdog helper that stays silent until a stable `/tmp/podcast-*/gurus-tech-bytes-*.mp3` exists, then prints a `MEDIA:` attachment line once per new MP3.
- `unifi_mcp.py` — read-only stdio MCP server and inventory CLI for the local UniFi Network API. It resolves `secret/UNIFI` at runtime via Vault MCP (or `UNIFI_API_KEY` / `UNIFI_BASE_URL` env vars), exposes safe inventory/query tools only, and can write a sanitized inventory summary with `--inventory --inventory-output <path>`.
- `unifi_ops.py` — deterministic, narrow UniFi client block/unblock helper for pinned local inventory. First run read-only preflight, e.g. `python scripts/unifi_ops.py block everett computer`, show the exact phrase `confirm block Everett computer`, then only after the user provides that exact phrase run `python scripts/unifi_ops.py block everett computer --confirm --request-source vanfam-telegram --source-context "$SIGNED_CONTEXT" --confirmation "confirm block Everett computer"` (or `unblock`) from an allowed source such as VanFam Telegram, SVA/AnITGuru DM, or local SVA operator session. Confirmed mutations fail closed if the confirmation text, `--request-source`, or short-lived HMAC `--source-context` is missing/untrusted/mismatched/expired; the helper verifies source context against a Vault-backed key from `secret/UNIFI` and does not trust caller-set environment variables as proof of Telegram/DM origin. It resolves `Everett computer` to MAC `1c:f6:4c:3a:e8:13` / IP `10.0.0.182`, uses pinned site `88f7af54-98f8-306a-a1c7-c9349722b1f6` and the official `/integration/v1/sites/{site}/clients/{client}/actions` endpoint, verifies afterward with a fresh client read, and never prints secrets.

Install script dependencies into the runtime venv that launches these helpers:

```bash
python -m pip install -r /Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/requirements.txt
```

The automations repo points at this directory through `HOME_OPS_HERMES_SCRIPTS`, defaulting to `/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts`.
