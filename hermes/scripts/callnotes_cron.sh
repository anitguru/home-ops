#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/Documents/Repos/Github/home-ops/hermes/callnotes"
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

if [[ "${1:-}" == "--check" ]]; then
  "$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_callnotes_env.py" --check
  "$PYTHON" -m py_compile callnotes.py "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_callnotes_env.py" "$HOME_OPS_HERMES_SCRIPTS/hermes_llm.py"
  eval "$("$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_callnotes_env.py")"
  export HOME_OPS_HERMES_SCRIPTS
  export HERMES_AUTOMATION_PROFILE="${HERMES_CALLNOTES_PROFILE:-callnotes}"
  export CALLNOTES_USE_LLM="0"
  "$PYTHON" callnotes.py --check --no-llm
  env -u HERMES_TUI -u HERMES_TUI_ACTIVE_SESSION_FILE -u HERMES_GATEWAY_SESSION -u HERMES_INTERACTIVE -u HERMES_SESSION_KEY \
    hermes -p "$HERMES_AUTOMATION_PROFILE" chat -Q --source callnotes-cron-check \
      -q 'Reply with exactly: callnotes profile ready'
  echo "callnotes_cron check ok"
  exit 0
fi

# Load Google Drive rclone secret from Vault MCP without writing it to a persistent rclone config.
eval "$("$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_callnotes_env.py")"

export HOME_OPS_HERMES_SCRIPTS
export HERMES_AUTOMATION_PROFILE="${HERMES_CALLNOTES_PROFILE:-callnotes}"
export CALLNOTES_USE_LLM="${CALLNOTES_USE_LLM:-1}"

"$PYTHON" callnotes.py "$@"

echo "home-ops callnotes run complete (Hermes cron only; no Gitea Actions, runners, Git push/writeback, or direct provider calls)"
