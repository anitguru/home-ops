#!/bin/zsh
# Refresh CocoIndex Code indexes for SVA-owned local KB/repos.
# Intended for user crontab; no Hermes/LLM credits required.

set -u

CCC="/Users/sva/.local/bin/ccc"
LOG_DIR="/Users/sva/Library/Logs/hermes"
LOG_FILE="$LOG_DIR/cocoindex-refresh.log"
LOCK_DIR="/tmp/sva-cocoindex-refresh.lock"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*" | tee -a "$LOG_FILE"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "Another CocoIndex refresh appears to be running; exiting."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

if [[ ! -x "$CCC" ]]; then
  log "ERROR: ccc not found or not executable at $CCC"
  exit 1
fi

PROJECTS=(
  "/Users/sva/Documents/Obsidian/AnITGuru"
  "/Users/sva/Documents/Repos/Gitea/automations"
  "/Users/sva/Documents/Repos/Gitea/observo"
  "/Users/sva/Documents/Repos/Github/anit.guru"
  "/Users/sva/Documents/Repos/Github/home-ops"
  "/Users/sva/Documents/Repos/Github/vanhero.com"
  "/Users/sva/Documents/Repos/Github/wayfinder.page"
)

log "Starting CocoIndex refresh for ${#PROJECTS[@]} projects"
overall_status=0

for project in "${PROJECTS[@]}"; do
  if [[ ! -d "$project" ]]; then
    log "SKIP missing project: $project"
    continue
  fi

  log "Indexing: $project"
  (
    cd "$project" || exit 1
    "$CCC" index
  ) >> "$LOG_FILE" 2>&1

  rc=$?
  if [[ $rc -ne 0 ]]; then
    log "ERROR indexing $project exited with $rc"
    overall_status=$rc
  else
    log "OK indexed: $project"
  fi
done

log "Finished CocoIndex refresh with status $overall_status"
exit $overall_status
