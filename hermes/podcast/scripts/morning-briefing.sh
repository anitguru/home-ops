#!/usr/bin/env bash
# morning-briefing.sh — Fetch top HN stories via Algolia API (domain dedup)
# Usage: PODCAST_DIR=/tmp/podcast-DATE ./morning-briefing.sh [num_stories]

set -euo pipefail

NUM_STORIES=${1:-20}
TARGET_STORIES=10
TODAY_DIR="${PODCAST_DIR:?PODCAST_DIR must be set}"
ALGOLIA_URL="https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=${NUM_STORIES}"

mkdir -p "$TODAY_DIR"

echo "[$(date)] Fetching top ${NUM_STORIES} HN stories from Algolia..."

curl -sf "$ALGOLIA_URL" > "${TODAY_DIR}/_hn_raw.json"

python3 - "${TODAY_DIR}" "${TARGET_STORIES}" <<'PYEOF'
import json, sys, urllib.parse

today_dir, target = sys.argv[1], int(sys.argv[2])

with open(f"{today_dir}/_hn_raw.json") as f:
    hits = json.load(f).get("hits", [])

seen_domains = set()
stories = []

for h in hits:
    url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
    domain = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    if domain in seen_domains:
        continue
    seen_domains.add(domain)
    stories.append({
        "id": h["objectID"],
        "title": h.get("title", "No title"),
        "url": url,
        "hn_url": f"https://news.ycombinator.com/item?id={h['objectID']}",
        "score": h.get("points") or 0,
        "comments": h.get("num_comments") or 0,
        "created_at": h.get("created_at", ""),
    })
    if len(stories) >= target:
        break

out_path = f"{today_dir}/stories.json"
with open(out_path, "w") as f:
    json.dump(stories, f, indent=2)

print(f"[done] {len(stories)} stories saved to {out_path}")
for s in stories:
    print(f"  [{s['score']:>4}pts/{s['comments']:>4}cmts] {s['title'][:70]}")
PYEOF

rm -f "${TODAY_DIR}/_hn_raw.json"
