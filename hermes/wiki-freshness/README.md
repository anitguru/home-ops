# Wiki freshness — Hermes cron runtime

Repo-backed home-ops runtime for the AnITGuru Obsidian wiki source freshness audit.

## Active scheduler

- **Owner:** default-profile Hermes cron job `Wiki freshness check`
- **Job ID:** `b4cff39d7b8e`
- **Script:** `wiki_freshness_cron.sh` via the profile-local launcher in `~/.hermes/scripts/`
- **Repo target:** `/Users/sva/Documents/Repos/Github/home-ops/hermes/wiki-freshness/`
- **Default scheduled workflow:** `wiki_repair.py --apply`, then `wiki_freshness.py --no-dry-run --no-llm --quiet`

The old Gitea schedule (`17 9 * * 1` UTC / Monday 09:17 UTC) is retired. The existing Hermes job intentionally keeps its already-configured schedule, `0 7 * * 1`. Hermes currently has no explicit timezone configured (`~/.hermes/config.yaml` has `timezone: ''`), so cron expressions are evaluated in the local scheduler timezone; current stored run timestamps show `-04:00`.

## What it does

1. Creates timestamped backups under `~/.hermes/backups/wiki-freshness/` before every mutation.
2. Repairs missing/invalid curated frontmatter from the page's already-valid schema folder.
3. Moves pages only when explicit frontmatter gives an unambiguous schema destination; collisions and unknown classifications fail safe.
4. Moves unmistakable imported captures into `40-wiki/raw/docs/imported-web-docs/`.
5. Adds missing curated pages to the correct section of `index.md`, and refreshes the date/count header.
6. Appends every repair to `40-wiki/log.md`.
7. Inventories source-backed Markdown, performs deterministic HTTP reachability checks, and appends attention items in live mode.

All local paths are containment-checked. Traversal, symlinked pages/control files,
and symlinked destination folders fail closed, and generated string frontmatter
is YAML-quoted. Source discovery accepts the schema fields `url`, `source_url`,
and `source`.

## Vault access

Default local mode uses:

```bash
VAULT_ROOT=/Users/sva/02-Areas/Personal
```

If the local vault path does not exist, the script can fall back to Obsidian MCP using:

- `OBSIDIAN_MCP_URL`
- `OBSIDIAN_MCP_TOKEN`
- `OBSIDIAN_MCP_VAULT` (defaults to `personal`)

Do not print token values. If secrets are needed for a future hosted/non-local run, load them through the SOPS+age `secret <vendor> <KEY>` helper or `home-ops/hermes/scripts/sops_env.py` rather than embedding them in cron definitions.

## LLM policy

Scheduled weekly quality stays deterministic with `--no-llm`. Structural repair does not need a model and never guesses an ambiguous destination.

Optional drift analysis is still available manually by omitting `--no-llm` or setting `WIKI_FRESHNESS_USE_LLM=1`. It calls `home-ops/hermes/scripts/hermes_llm.py`, which launches subscription-backed Hermes one-shots and strips legacy direct-provider / nested session environment variables. It does **not** use direct Claude/Anthropic SDKs or CLIs.

## Manual commands

From this directory:

```bash
/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python wiki_freshness.py --help
/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python wiki_freshness.py --dry-run --no-llm --limit 5
/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python wiki_repair.py --vault /Users/sva/02-Areas/Personal
/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/wiki_freshness_cron.sh --check
```

To run through Hermes cron without changing the schedule:

```bash
hermes cron run b4cff39d7b8e
HERMES_ACCEPT_HOOKS=1 hermes cron tick
```

Inspect cron output under `~/.hermes/cron/output/b4cff39d7b8e/` if delivery is ambiguous.
