#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/01-Projects/home-ops"
CONFIG="$ROOT/hermes/file-organizer/file-organization.json"
source "$ROOT/hermes/scripts/para_pipeline_lock.sh"

if ! acquire_para_pipeline_lock; then
  exit 0
fi

if ! run_para_pipeline_command python3 "$ROOT/hermes/scripts/user_file_organizer.py" --config "$CONFIG" --apply; then
  OUTPUT="$HERMES_PARA_OUTPUT"
  printf 'Hermes: PARA file maintenance failed.\n%s\n' "$OUTPUT"
  exit 1
fi
OUTPUT="$HERMES_PARA_OUTPUT"

if ! ERRORS=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["counts"].get("errors", 1))' <<<"$OUTPUT" 2>/dev/null); then
  printf 'Hermes: PARA file maintenance returned invalid output.\n%s\n' "$OUTPUT"
  exit 1
fi
if [[ "$ERRORS" != "0" ]]; then
  printf 'Hermes: PARA file maintenance completed with errors.\n%s\n' "$OUTPUT"
  exit 1
fi

SUMMARY=$(python3 -c '
import json,sys
x=json.load(sys.stdin); c=x["counts"]
if c.get("moved",0) or c.get("trashed",0):
 print("Hermes: PARA file maintenance moved {moved}, trashed {trashed}, needs review {reported}, blocked by cap {blocked}. Report: {report}".format(moved=c.get("moved",0), trashed=c.get("trashed",0), reported=c.get("reported",0), blocked=c.get("blocked",0), report=x["report"]))
' <<<"$OUTPUT")

if [[ -n "$SUMMARY" ]]; then
  printf '%s\n' "$SUMMARY"
fi
