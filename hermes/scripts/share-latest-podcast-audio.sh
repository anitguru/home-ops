#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HERMES_STATE_DIR:-$HOME/.hermes/state}"
STATE_FILE="$STATE_DIR/latest-podcast-audio-shared.txt"
mkdir -p "$STATE_DIR"

# Podcast pipeline docs currently write per-episode artifacts under /tmp/podcast-YYYY-MM-DD/.
# Stay silent until a stable, non-empty MP3 exists; Hermes no-agent cron treats empty stdout as no delivery.
latest="$(find /tmp -maxdepth 2 -type f -path '/tmp/podcast-*/gurus-tech-bytes-*.mp3' -size +100k -print0 2>/dev/null \
  | xargs -0 stat -f '%m %N' 2>/dev/null \
  | sort -nr \
  | head -n 1 \
  | cut -d' ' -f2- || true)"

[[ -n "${latest:-}" ]] || exit 0
[[ -f "$latest" ]] || exit 0

now="$(date +%s)"
mtime="$(stat -f '%m' "$latest")"
# Avoid sending a file that is still being written.
if (( now - mtime < 60 )); then
  exit 0
fi

sent=""
if [[ -f "$STATE_FILE" ]]; then
  sent="$(cat "$STATE_FILE" || true)"
fi

if [[ "$sent" == "$latest" ]]; then
  exit 0
fi

printf '%s\n' "$latest" > "$STATE_FILE"
printf 'Podcast audio complete:\nMEDIA:%s\n' "$latest"
