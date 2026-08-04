#!/usr/bin/env bash
set -euo pipefail

TODAY=${TODAY:-$(date +%Y-%m-%d)}
PODCAST_DIR=${PODCAST_DIR:-/tmp/podcast-$TODAY}
SCRIPT_PATH=${SCRIPT_PATH:-$PODCAST_DIR/script.txt}
TTS_URL=${TTS_URL:-https://chatterbox.transformers.lan/v1/audio/speech}
# Optional Tailscale/MagicDNS transport host. The URL hostname remains the TLS
# identity because the current service certificate is issued to
# chatterbox.transformers.lan, not the *.tail099001.ts.net transport name.
TTS_CONNECT_HOST=${TTS_CONNECT_HOST:-}
TTS_VOICE=${TTS_VOICE:-peter-griffin.wav}
TTS_MODEL=${TTS_MODEL:-tts-1}
TTS_SPEED=${TTS_SPEED:-1.0}
TTS_LOUDNORM=${TTS_LOUDNORM:-I=-16:TP=-1.5:LRA=11}
MIN_DURATION_SECONDS=${MIN_DURATION_SECONDS:-60}

CURL_CONNECT_ARGS=()
if [[ -n "$TTS_CONNECT_HOST" ]]; then
  TTS_URL_HOST=$(python3 - "$TTS_URL" <<'PY'
import sys
from urllib.parse import urlparse
parsed = urlparse(sys.argv[1])
if parsed.scheme != "https" or not parsed.hostname:
    raise SystemExit(f"TTS_CONNECT_HOST requires an https TTS_URL, got: {sys.argv[1]}")
print(parsed.hostname)
PY
)
  TTS_URL_PORT=$(python3 - "$TTS_URL" <<'PY'
import sys
from urllib.parse import urlparse
parsed = urlparse(sys.argv[1])
print(parsed.port or 443)
PY
)
  CURL_CONNECT_ARGS=(--connect-to "${TTS_URL_HOST}:${TTS_URL_PORT}:${TTS_CONNECT_HOST}:${TTS_URL_PORT}")
fi

MP3="$PODCAST_DIR/gurus-tech-bytes-$TODAY.mp3"
SEGMENTS_DIR="$PODCAST_DIR/segments"
mkdir -p "$SEGMENTS_DIR"

if [[ ! -s "$SCRIPT_PATH" ]]; then
  echo "ERROR: script not found or empty: $SCRIPT_PATH" >&2
  exit 2
fi

python3 - "$SCRIPT_PATH" "$SEGMENTS_DIR" <<'PY'
import pathlib, sys
script = pathlib.Path(sys.argv[1]).read_text().strip()
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
segments = [p.strip() for p in script.split("\n\n") if p.strip()]
if not segments:
    raise SystemExit("no script segments found")
for i, segment in enumerate(segments, 1):
    (out / f"segment-{i:02d}.txt").write_text(segment)
PY

count=$(find "$SEGMENTS_DIR" -name 'segment-*.txt' | wc -l | tr -d ' ')
echo "[tts] Generating $count Chatterbox segment(s) via $TTS_URL"
if [[ -n "$TTS_CONNECT_HOST" ]]; then
  echo "[tts] Connecting through Tailscale host $TTS_CONNECT_HOST with TLS identity $TTS_URL_HOST"
fi

# Max whole-request attempts per segment. curl's own --retry covers sub-second
# blips; this outer loop (with real backoff) survives a longer chatterbox
# endpoint outage — e.g. a 30-60s restart — that would otherwise fail the episode.
TTS_MAX_ATTEMPTS=${TTS_MAX_ATTEMPTS:-5}
# TTS endpoints tried in order: primary ($TTS_URL) first, then optional fallback
# ($TTS_URL_FALLBACK). A dead/absent primary — e.g. the rgb GPU host powered off
# — fails fast (connection refused) and the loop rides over to the fallback
# (metroplex CPU) immediately, so the episode still ships. Leave TTS_URL_FALLBACK
# empty for single-endpoint behavior.
TTS_URL_FALLBACK=${TTS_URL_FALLBACK:-}
TTS_URLS=("$TTS_URL")
if [[ -n "$TTS_URL_FALLBACK" && "$TTS_URL_FALLBACK" != "$TTS_URL" ]]; then
  TTS_URLS+=("$TTS_URL_FALLBACK")
  echo "[tts] primary=$TTS_URL fallback=$TTS_URL_FALLBACK"
fi
: > "$SEGMENTS_DIR/concat.txt"
for txt in "$SEGMENTS_DIR"/segment-*.txt; do
  base=${txt%.txt}
  json="$base.json"
  mp3="$base.mp3"
  python3 - "$txt" "$json" "$TTS_MODEL" "$TTS_VOICE" "$TTS_SPEED" <<'PY'
import json, pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
payload = {
    "model": sys.argv[3],
    "input": text,
    "voice": sys.argv[4],
    "response_format": "mp3",
    "speed": float(sys.argv[5]),
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload))
PY
  attempt=1
  while :; do
    idx=$(( attempt - 1 )); (( idx >= ${#TTS_URLS[@]} )) && idx=$(( ${#TTS_URLS[@]} - 1 ))
    url="${TTS_URLS[$idx]}"
    cargs=(); [[ "$url" == "$TTS_URL" ]] && cargs=("${CURL_CONNECT_ARGS[@]}")   # Tailscale connect-to only valid for primary
    echo "[tts] POST $(basename "$mp3") (attempt $attempt/$TTS_MAX_ATTEMPTS via $url)"
    ok=1
    curl "${cargs[@]}" -fsS --retry 2 --retry-all-errors --connect-timeout 30 --max-time 900 \
      -X POST "$url" \
      -H "Content-Type: application/json" \
      --data-binary "@$json" \
      -o "$mp3" || ok=0
    bytes=0
    [[ -f "$mp3" ]] && bytes=$(wc -c < "$mp3" | tr -d ' ')
    if [[ "$ok" = 1 && "$bytes" -ge 5000 ]]; then
      duration=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$mp3")
      echo "[tts] $(basename "$mp3") ${bytes} bytes ${duration}s (via $url)"
      break
    fi
    if [[ "$attempt" -ge "$TTS_MAX_ATTEMPTS" ]]; then
      echo "ERROR: TTS segment failed after $TTS_MAX_ATTEMPTS attempts: $mp3 (curl_ok=$ok bytes=$bytes)" >&2
      exit 3
    fi
    # If the next attempt switches to a different endpoint, fail over immediately (no backoff).
    nidx=$attempt; (( nidx >= ${#TTS_URLS[@]} )) && nidx=$(( ${#TTS_URLS[@]} - 1 ))
    if [[ "${TTS_URLS[$nidx]}" != "$url" ]]; then backoff=0; else backoff=$(( attempt * 15 )); fi
    echo "[tts] $(basename "$mp3") failed on $url (curl_ok=$ok bytes=$bytes) — next attempt in ${backoff}s" >&2
    rm -f "$mp3"
    sleep "$backoff"
    attempt=$(( attempt + 1 ))
  done
  printf "file '%s'\n" "$mp3" >> "$SEGMENTS_DIR/concat.txt"
done

joined_tmp="$MP3.joined.tmp.mp3"
normalized_tmp="$MP3.normalized.tmp.mp3"
ffmpeg -hide_banner -y -f concat -safe 0 -i "$SEGMENTS_DIR/concat.txt" -c copy "$joined_tmp"

if [[ -n "$TTS_LOUDNORM" ]]; then
  echo "[tts] Applying loudness normalization: loudnorm=$TTS_LOUDNORM"
  ffmpeg -hide_banner -y -i "$joined_tmp" -af "loudnorm=$TTS_LOUDNORM" -ar 24000 -ac 1 -codec:a libmp3lame -b:a 64k "$normalized_tmp"
  mv "$normalized_tmp" "$MP3"
else
  mv "$joined_tmp" "$MP3"
fi
rm -f "$joined_tmp" "$normalized_tmp"

duration=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$MP3")
bytes=$(wc -c < "$MP3" | tr -d ' ')
python3 - "$duration" "$MIN_DURATION_SECONDS" <<'PY'
import sys
if float(sys.argv[1]) < float(sys.argv[2]):
    raise SystemExit(f"duration too short: {sys.argv[1]}s")
PY

echo "[tts] Wrote $MP3 (${bytes} bytes, ${duration}s)"
