#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/Documents/Repos/Github/home-ops/hermes/x-social"
HOME_OPS_HERMES_SCRIPTS="${HOME_OPS_HERMES_SCRIPTS:-/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/sva/.hermes/hermes-agent/venv/bin/python3}"
PYTHON="${PYTHON:-/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python}"
X_SOCIAL_STATE_DIR="${X_SOCIAL_STATE_DIR:-${HERMES_STATE_DIR:-$HOME/.local/state/home-ops}/x-social}"
OBSIDIAN_VAULT="${OBSIDIAN_VAULT:-/Users/sva/Library/CloudStorage/GoogleDrive-admin@vanhero.com/My Drive/Obsidian/AnITGuru}"

cd "$ROOT"

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "ERROR: expected Hermes venv Python at $HERMES_PYTHON" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: expected home-ops venv Python at $PYTHON" >&2
  echo "Create it with: $HERMES_PYTHON -m venv /Users/sva/Documents/Repos/Github/home-ops/.venv && /Users/sva/Documents/Repos/Github/home-ops/.venv/bin/pip install -r $ROOT/requirements.txt" >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  "$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_social_env.py" --purpose post --check
  "$PYTHON" -m py_compile scripts/fetch_metrics.py scripts/growth_audit.py scripts/social_db.py scripts/state_paths.py
  env -u HERMES_TUI -u HERMES_TUI_ACTIVE_SESSION_FILE -u HERMES_GATEWAY_SESSION -u HERMES_INTERACTIVE -u HERMES_SESSION_KEY \
    hermes -p xposting chat -Q --source x-growth-audit-check --provider xai-oauth -m grok-4.3 --toolsets terminal \
      -q 'Return exactly: grok weekly audit profile ready'
  echo "weekly_x_growth_audit_cron check ok"
  exit 0
fi

# Load X/Tavily/Postgres secrets from Vault MCP without writing them to disk.
# fetch_metrics is read-only and refreshes the local performance ledger before audit.
eval "$("$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/vault_mcp_social_env.py" --purpose post)"

export HOME_OPS_HERMES_SCRIPTS
export X_SOCIAL_STATE_DIR
export OBSIDIAN_VAULT
export HERMES_AUDIT_PROFILE="${HERMES_AUDIT_PROFILE:-xposting}"
export HERMES_AUTOMATION_TOOLSETS="${HERMES_AUTOMATION_TOOLSETS:-terminal}"
export GROK_AUDIT_PROVIDER="${GROK_AUDIT_PROVIDER:-xai-oauth}"
export GROK_AUDIT_MODEL="${GROK_AUDIT_MODEL:-grok-4.3}"
export X_GROWTH_AUTOTUNE_CRONS="${X_GROWTH_AUTOTUNE_CRONS:-1}"

LOG_DIR="$X_SOCIAL_STATE_DIR/logs"
mkdir -p "$LOG_DIR"
export X_GROWTH_FETCH_METRICS_LOG="$LOG_DIR/weekly_x_growth_audit_fetch_metrics.log"

if "$PYTHON" scripts/fetch_metrics.py >"$X_GROWTH_FETCH_METRICS_LOG" 2>&1; then
  export X_GROWTH_FETCH_METRICS_SUCCESS=1
else
  export X_GROWTH_FETCH_METRICS_SUCCESS=0
  echo "WARN: fetch_metrics failed; continuing with existing local ledger (log: $X_GROWTH_FETCH_METRICS_LOG)" >&2
fi
"$PYTHON" scripts/growth_audit.py
