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
export VAULT_ROOT="${VAULT_ROOT:-/Users/sva/Documents/Dropbox/Obsidian/AnITGuru}"
export OBSIDIAN_MCP_VAULT="${OBSIDIAN_MCP_VAULT:-personal}"

if [[ "${1:-}" == "--check" ]]; then
  "$PYTHON" -m py_compile wiki_freshness.py "$HOME_OPS_HERMES_SCRIPTS/hermes_llm.py"
  "$PYTHON" - <<'PY'
import httpx
print(f"httpx ok ({httpx.__version__})")
PY
  "$PYTHON" wiki_freshness.py --help >/dev/null
  "$PYTHON" wiki_freshness.py --dry-run --no-llm --limit 1
  echo "wiki_freshness_cron check ok"
  exit 0
fi

# Weekly scheduled path stays deterministic: dry-run + no LLM unless a human
# explicitly passes different CLI flags to this wrapper.
if [[ "$#" -eq 0 ]]; then
  set -- --dry-run --no-llm
fi

"$PYTHON" wiki_freshness.py "$@"

echo "home-ops wiki-freshness run complete (Hermes cron only; no Gitea Actions, runners, Git push/writeback, or direct provider calls)"
