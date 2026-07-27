#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/01-Projects/home-ops"
CONFIG="$ROOT/hermes/file-organizer/file-organization.json"
LOCKDIR="/tmp/hermes-para-file-namer.lock"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

if ! OUTPUT=$(python3 "$ROOT/hermes/scripts/para_file_namer.py" --config "$CONFIG" 2>&1); then
  printf 'Hermes: local PARA naming prep failed.\n%s\n' "$OUTPUT"
  exit 1
fi

ERRORS=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("errors", 1))' <<<"$OUTPUT" 2>/dev/null || printf '1')
if [[ "$ERRORS" != "0" ]]; then
  printf 'Hermes: local PARA naming prep completed with errors.\n%s\n' "$OUTPUT"
  exit 1
fi

# Successful proposal generation is intentionally silent; the apply stage reports real actions.
