#!/usr/bin/env bash
# Guru's Tech Bytes — pi4 daily producer (Approach B: deterministic pipeline,
# claude -p only for the script). Replaces the Mac Hermes cron job a694c08ba15f.
#
#   DRY_RUN=1  -> produce all artifacts but SKIP Cloudinary/publish/git push/DB
#                 upsert and send a short text summary instead of media.
#   (default)  -> full produce + publish + DB upsert + Telegram media delivery.
set -uo pipefail

export PATH="/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin"
export TZ=America/New_York

HOME_OPS=/home/pi/home-ops
SITE_DIR=/home/pi/anit.guru
PY="$HOME_OPS/.venv/bin/python"
SECRET=/home/pi/.local/bin/secret
CHAT_ID=8100669692
DRY_RUN="${DRY_RUN:-0}"
# --- script LLM: swap provider/model here. FALLBACK = set these back to
#     claude / claude-opus-4-8 (or run with SCRIPT_PROVIDER=claude override). ---
export SCRIPT_PROVIDER="${SCRIPT_PROVIDER:-ollama}"        # claude | ollama
export SCRIPT_MODEL="${SCRIPT_MODEL:-glm-5.2}"             # claude-opus-4-8 | glm-5.2
export OLLAMA_CLOUD_API_KEY="${OLLAMA_CLOUD_API_KEY:-$($SECRET ollama CLOUD_API_KEY)}"
# --- TTS endpoints: chatterbox_tts_segments.sh tries $TTS_URL first, then
#     $TTS_URL_FALLBACK on failure (fast failover). Default = metroplex CPU only.
#     To PREFER the rgb 4090 GPU host once its chatterbox is live+verified,
#     uncomment these two (metroplex stays as the always-there fallback):
# export TTS_URL="https://rgb.transformers.lan:4123/v1/audio/speech"
# export TTS_URL_FALLBACK="https://chatterbox.transformers.lan/v1/audio/speech"

TODAY=$(date +%F)
DAY_NAME=$(date +%A)
PODCAST_DIR="${PODCAST_DIR:-/tmp/podcast-$TODAY}"
mkdir -p "$PODCAST_DIR"
LOG="$PODCAST_DIR/run.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== $(date '+%F %T %Z') run start (DRY_RUN=$DRY_RUN model=$SCRIPT_MODEL) ====="

BOT_TOKEN="$($SECRET telegram BOT_TOKEN)"
tg_msg(){ curl -sf "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
  --data-urlencode "chat_id=$CHAT_ID" --data-urlencode "text=$1" >/dev/null || true; }
tg_audio(){ curl -sf -F "chat_id=$CHAT_ID" -F "audio=@$1" "https://api.telegram.org/bot$BOT_TOKEN/sendAudio" >/dev/null || true; }
tg_doc(){ curl -sf -F "chat_id=$CHAT_ID" -F "document=@$1" "https://api.telegram.org/bot$BOT_TOKEN/sendDocument" >/dev/null || true; }

fail(){
  echo "FAIL at: $*"
  tg_msg "🔴 Guru's Tech Bytes ($TODAY) FAILED at: $*
log: $LOG
$(tail -n 6 "$LOG" 2>/dev/null)"
  exit 1
}

cd "$HOME_OPS/hermes/podcast" || fail "cd podcast dir"

# --- secrets (podcast purpose) ---
eval "$("$PY" "$HOME_OPS/hermes/scripts/sops_env.py" --purpose podcast)" || fail "load secrets"
unset TTS_CONNECT_HOST WHISPER_CONNECT_HOST   # pi4 is on-LAN; direct to *.transformers.lan

MP3="$PODCAST_DIR/gurus-tech-bytes-$TODAY.mp3"
SRT="$PODCAST_DIR/gurus-tech-bytes-$TODAY.srt"

# --- STEP 0: episode number (reuse same-day; else max+1) ---
EPISODE_NUM=$("$PY" - "$TODAY" <<'PY'
import psycopg, os, sys
with psycopg.connect(os.environ['COCOINDEX_DATABASE_URL']) as c, c.cursor() as cur:
    cur.execute("SELECT episode FROM podcast_episodes WHERE date=%s", (sys.argv[1],))
    r = cur.fetchone()
    if r: print(r[0])
    else:
        cur.execute("SELECT COALESCE(MAX(episode),0)+1 FROM podcast_episodes"); print(cur.fetchone()[0])
PY
) || fail "episode number lookup"
[ -n "$EPISODE_NUM" ] || fail "empty episode number"
printf '{"episode": %s, "date": "%s"}\n' "$EPISODE_NUM" "$TODAY" > "$PODCAST_DIR/metadata.json"
echo "[step0] episode=$EPISODE_NUM date=$TODAY ($DAY_NAME)"

# --- STEP 1: fetch HN stories ---
PODCAST_DIR="$PODCAST_DIR" bash scripts/morning-briefing.sh || fail "story fetch"
NST=$("$PY" -c "import json;print(len(json.load(open('$PODCAST_DIR/stories.json'))))")
[ "$NST" -ge 5 ] || fail "only $NST stories (<5)"

# --- STEP 1.5: rank + hard proof gate ---
"$PY" scripts/cocoindex_rank.py "$PODCAST_DIR" 2>&1 | tee "$PODCAST_DIR/rank.log"
grep -qF '[cocoindex] Top trending:' "$PODCAST_DIR/rank.log" || fail "rank: no 'Top trending' proof"
grep -qE '\[cocoindex\] Loaded [0-9]+ recent podcast story keys for dedupe' "$PODCAST_DIR/rank.log" || fail "rank: no dedupe proof"
if grep -qF 'Topic index unavailable' "$PODCAST_DIR/rank.log"; then fail "rank: CocoIndex fallback (do not publish)"; fi

# --- STEP 2: author script.txt + selected-stories.json via claude -p ---
"$PY" scripts/pi4_generate_script.py "$PODCAST_DIR" "$EPISODE_NUM" "$DAY_NAME" || fail "script generation"

# --- STEP 3: Chatterbox TTS ---
TODAY="$TODAY" PODCAST_DIR="$PODCAST_DIR" bash scripts/chatterbox_tts_segments.sh || fail "TTS"
[ -s "$MP3" ] || fail "MP3 missing"
DUR=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$MP3")
"$PY" -c "import sys;sys.exit(0 if float('$DUR')>60 else 1)" || fail "MP3 duration ${DUR}s <= 60"
echo "[step3] MP3 ${DUR}s"

# --- STEP 4: Whisper -> SRT ---
curl -fsS "$WHISPER_URL" -F "file=@$MP3" -F "response_format=verbose_json" -F "language=en" \
  --max-time 900 -o "$PODCAST_DIR/whisper-raw.json" || fail "whisper transcription"
"$PY" scripts/pi4_build_srt.py "$PODCAST_DIR" "$TODAY" || fail "SRT build"
rm -f "$PODCAST_DIR/whisper-raw.json"
[ -s "$SRT" ] || fail "SRT missing"

# --- summary line ---
TITLES=$("$PY" -c "import json;print('\n'.join('- '+s['title'] for s in json.load(open('$PODCAST_DIR/selected-stories.json'))))")

if [ "$DRY_RUN" = "1" ]; then
  echo "[dry-run] skipping publish/DB/media"
  tg_msg "🟡 Guru's Tech Bytes DRY RUN — Ep $EPISODE_NUM ($TODAY)
MP3 ${DUR}s, SRT ok. NOT published.
Stories:
$TITLES"
  echo "===== dry run OK ====="
  exit 0
fi

# --- STEP 5: publish (Cloudinary + episode md + git push -> Netlify) ---
git -C "$SITE_DIR" pull --rebase --autostash origin main >/dev/null 2>&1 || true
export CLOUDINARY_CLOUD_NAME CLOUDINARY_API_KEY CLOUDINARY_API_SECRET
PUB=$(cd "$SITE_DIR" && PODCAST_DIR="$PODCAST_DIR" node scripts/publish-episode.mjs "$TODAY" "$PODCAST_DIR/selected-stories.json" 2>&1) || { echo "$PUB"; fail "publish-episode.mjs"; }
echo "$PUB"
AUDIO_URL=$(printf '%s\n' "$PUB" | "$PY" -c "import sys,json
for line in sys.stdin:
    line=line.strip()
    if line.startswith('{'):
        try: print(json.loads(line).get('audioUrl','')); break
        except Exception: pass")
[ -n "$AUDIO_URL" ] || fail "publish produced no audioUrl"
echo "[step5] audioUrl=$AUDIO_URL"

# --- STEP 6: DB upsert ---
AUDIO_URL="$AUDIO_URL" EPISODE_NUM="$EPISODE_NUM" TODAY="$TODAY" PODCAST_DIR="$PODCAST_DIR" "$PY" - <<'PY' || fail "DB upsert"
import psycopg, json, os
with open(os.environ["PODCAST_DIR"] + "/selected-stories.json") as f:
    stories = json.dumps(json.load(f))
with psycopg.connect(os.environ["COCOINDEX_DATABASE_URL"]) as conn, conn.cursor() as cur:
    cur.execute("""
        INSERT INTO podcast_episodes (date, episode, stories, audio_url)
        VALUES (%s,%s,%s::jsonb,%s)
        ON CONFLICT (date) DO UPDATE SET
            episode=EXCLUDED.episode, stories=EXCLUDED.stories,
            audio_url=EXCLUDED.audio_url, published_at=now()
    """, (os.environ["TODAY"], int(os.environ["EPISODE_NUM"]), stories, os.environ["AUDIO_URL"]))
    conn.commit()
print("[step6] DB upsert OK")
PY

# --- STEP 7: Telegram delivery ---
tg_msg "🎙️ Guru's Tech Bytes Ep. $EPISODE_NUM — $TODAY
Status: SUCCESS
Cloudinary: $AUDIO_URL
Stories:
$TITLES"
tg_audio "$MP3"
tg_doc "$SRT"
echo "===== run OK: Ep $EPISODE_NUM published ====="
