#!/usr/bin/env bash
set -euo pipefail

# AI News Radar — scans Apple Mail + Proton Bridge every four hours for strict,
# high-impact AI news, posts to X, and logs to the existing Postgres posts table.

ROOT="/Users/sva/01-Projects/home-ops/hermes/x-social"
HOME_OPS_HERMES_SCRIPTS="${HOME_OPS_HERMES_SCRIPTS:-/Users/sva/.hermes/scripts}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/sva/.hermes/hermes-agent/venv/bin/python3}"
PYTHON="${PYTHON:-/Users/sva/01-Projects/home-ops/.venv/bin/python}"
X_SOCIAL_STATE_DIR="${X_SOCIAL_STATE_DIR:-${HERMES_STATE_DIR:-$HOME/.local/state/home-ops}/x-social}"

cd "$ROOT"

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "ERROR: expected Hermes venv Python at $HERMES_PYTHON" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: expected home-ops venv Python at $PYTHON" >&2
  echo "Create it with: $HERMES_PYTHON -m venv /Users/sva/01-Projects/home-ops/.venv && /Users/sva/01-Projects/home-ops/.venv/bin/pip install -r $ROOT/requirements.txt" >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  "$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/sops_env.py" --purpose radar --check
  "$PYTHON" -m py_compile scripts/radar.py scripts/social_db.py
  echo "radar_actions_cron check ok"
  exit 0
fi

# Quiet hours: skip 23:00–08:00 ET
HOUR_ET="$(TZ="America/New_York" date +%H)"
if [[ "$HOUR_ET" -ge 23 || "$HOUR_ET" -lt 8 ]]; then
  echo "Quiet hours (${HOUR_ET}:xx ET) — skipping radar run"
  exit 0
fi

# Load X/Postgres secrets from the local SOPS+age store without writing plaintext to disk.
eval "$("$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/sops_env.py" --purpose radar)"

export HOME_OPS_HERMES_SCRIPTS
export X_SOCIAL_STATE_DIR
export HERMES_AUTOMATION_PROFILE="${HERMES_RADAR_PROFILE:-xposting}"
export HERMES_AUTOMATION_TOOLSETS="${HERMES_AUTOMATION_TOOLSETS:-terminal}"
export RADAR_USE_LLM="${RADAR_USE_LLM:-1}"
export RADAR_TRIAGE_LLM="${RADAR_TRIAGE_LLM:-1}"
# Local Ollama Qwen for triage + draft (override with RADAR_LLM_PROVIDER/RADAR_LLM_MODEL)
export RADAR_LLM_PROVIDER="${RADAR_LLM_PROVIDER:-ollama-local}"
export RADAR_LLM_MODEL="${RADAR_LLM_MODEL:-qwen3.6:35b-a3b}"

"$PYTHON" scripts/radar.py

echo "radar run complete (state under $X_SOCIAL_STATE_DIR)"