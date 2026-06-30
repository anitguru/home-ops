# Docs wishlist Hermes cron

Repo-backed runtime for the migrated `docs-wishlist` automation.

## Active scheduler

- Scheduler: default Hermes cron, not Gitea Actions.
- Launcher: `~/.hermes/scripts/docs_wishlist_cron.sh` → `home-ops/hermes/scripts/docs_wishlist_cron.sh`.
- Runtime: `home-ops/hermes/docs-wishlist/rss_ingest.py`.
- Default mode: deterministic live ingest (`--no-dry-run`), `RSS_INGEST_USE_LLM=0`. Pass `--dry-run` manually for audits.
- Default vault: local filesystem at `/Users/sva/02-Areas/Personal` via `VAULT_ROOT`; imported docs are written under `40-wiki/raw/docs/imported-web-docs/`, with activity appended to `40-wiki/log.md`.
- Default scraper: self-hosted Firecrawl at `https://10.0.0.53`; bearer token comes from `FIRECRAWL_API_KEY` or `FIRECRAWL_API_TOKEN` if available in the environment / `~/.hermes/.env`.

## Manual checks

```bash
/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/docs_wishlist_cron.sh --check
```

Dry-run all configured sites:

```bash
/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/docs_wishlist_cron.sh --site all --cap 5 --dry-run
```

Live run for one site, only after reviewing output:

```bash
/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/docs_wishlist_cron.sh --site react --cap 1 --no-dry-run
```

## Notes

- Gitea `.gitea/workflows/docs-wishlist.yml` is manual-only now to prevent duplicate scheduled ingestion while the repo is retired.
- This runtime intentionally avoids the old Obsidian MCP dependency when local vault files are available.
- Keep generated/raw wiki output in the Obsidian vault, not in this repo.
