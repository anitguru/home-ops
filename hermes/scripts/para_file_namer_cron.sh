#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/01-Projects/home-ops"
CONFIG="$ROOT/hermes/file-organizer/file-organization.json"
source "$ROOT/hermes/scripts/para_pipeline_lock.sh"

if ! acquire_para_pipeline_lock; then
  exit 0
fi

if ! run_para_pipeline_command python3 "$ROOT/hermes/scripts/para_file_namer.py" --config "$CONFIG"; then
  OUTPUT="$HERMES_PARA_OUTPUT"
  printf 'Hermes: local PARA naming prep failed.\n%s\n' "$OUTPUT"
  exit 1
fi
OUTPUT="$HERMES_PARA_OUTPUT"

ERRORS=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("errors", 1))' <<<"$OUTPUT" 2>/dev/null || printf '1')
if [[ "$ERRORS" != "0" ]]; then
  printf 'Hermes: local PARA naming prep completed with errors.\n%s\n' "$OUTPUT"
  exit 1
fi

# Successful proposal generation is intentionally silent; the apply stage reports real actions.
