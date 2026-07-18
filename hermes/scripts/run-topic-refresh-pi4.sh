#!/usr/bin/env bash
# pi4 CocoIndex HN topic-refresh — feeds cocoindex_rank's trending signal.
# Uses claude -p (Sonnet) via hermes-shim instead of the Mac `hermes` CLI.
#   run-topic-refresh-pi4.sh          -> dry run (no DB write)
#   run-topic-refresh-pi4.sh --write  -> persist rows to Supabase topic table
set -uo pipefail
export PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin
export TZ=America/New_York
HOME_OPS=/home/pi/home-ops
PY="$HOME_OPS/.venv/bin/python"
export HERMES_BIN="$HOME_OPS/hermes/bin/hermes-shim"
export HERMES_SHIM_MODEL="${HERMES_SHIM_MODEL:-claude-sonnet-5}"
LOG="/tmp/topic-refresh-$(date +%F).log"
exec > >(tee -a "$LOG") 2>&1
echo "===== $(date '+%F %T %Z') topic-refresh (model=$HERMES_SHIM_MODEL, args=$*) ====="
cd "$HOME_OPS/hermes/scripts" || exit 1
eval "$("$PY" sops_env.py --purpose podcast)" || { echo "secrets load failed"; exit 1; }
"$PY" hn_topic_refresh_hermes.py "$@"
