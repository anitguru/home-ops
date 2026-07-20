#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/Documents/Repos/Github/home-ops/hermes/wiki-freshness"
HOME_OPS_HERMES_SCRIPTS="${HOME_OPS_HERMES_SCRIPTS:-/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/sva/.hermes/hermes-agent/venv/bin/python3}"
PYTHON="${PYTHON:-/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python}"

# Prevent legacy direct-provider and nested Hermes/TUI env from leaking into child one-shots.
unset ANTHROPIC_API_KEY ANTHROPIC_TOKEN CLAUDE_API_KEY
unset HERMES_TUI HERMES_TUI_ACTIVE_SESSION_FILE HERMES_GATEWAY_SESSION HERMES_INTERACTIVE HERMES_SESSION_KEY

cd "$ROOT"

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "ERROR: expected Hermes venv Python at $HERMES_PYTHON" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: expected home-ops venv Python at $PYTHON" >&2
  echo "Create it with: $HERMES_PYTHON -m venv /Users/sva/Documents/Repos/Github/home-ops/.venv && /Users/sva/Documents/Repos/Github/home-ops/.venv/bin/pip install -r /Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/requirements.txt" >&2
  exit 1
fi

export HOME_OPS_HERMES_SCRIPTS
export WIKI_FRESHNESS_USE_LLM="${WIKI_FRESHNESS_USE_LLM:-0}"
export VAULT_ROOT="${VAULT_ROOT:-/Users/sva/02-Areas/Personal}"
export OBSIDIAN_MCP_VAULT="${OBSIDIAN_MCP_VAULT:-personal}"

if [[ "${1:-}" == "--check" ]]; then
  "$PYTHON" -m py_compile wiki_freshness.py wiki_repair.py "$HOME_OPS_HERMES_SCRIPTS/hermes_llm.py"
  "$PYTHON" - <<'PY'
import httpx
print(f"httpx ok ({httpx.__version__})")
PY
  "$PYTHON" wiki_freshness.py --help >/dev/null
  "$PYTHON" wiki_repair.py --vault "$VAULT_ROOT"
  "$PYTHON" wiki_freshness.py --dry-run --no-llm --quiet --limit 1
  echo "wiki_freshness_cron check ok"
  exit 0
fi

# Weekly scheduled path stays deterministic and backup-first. It applies only
# unambiguous schema/index/path repairs, then performs a live no-LLM source URL
# audit. Ambiguous moves and destination collisions fail safe and are reported.
if [[ "$#" -eq 0 ]]; then
  "$PYTHON" wiki_repair.py --vault "$VAULT_ROOT" --apply
  "$PYTHON" wiki_freshness.py --vault "$VAULT_ROOT" --no-dry-run --no-llm --quiet
else
  "$PYTHON" wiki_freshness.py "$@"
fi

echo "home-ops wiki maintenance/freshness run complete (backup-first deterministic repairs; no Gitea Actions, runners, Git push/writeback, or direct provider calls)"
