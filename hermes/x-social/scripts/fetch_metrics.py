#!/usr/bin/env python3
"""
Fetch public engagement metrics for recent tweets and update state/posts.jsonl.
Run before each post cycle so updated metrics are committed alongside the new post.
"""
import json
import os
import sys
import time
from pathlib import Path

import tweepy

try:
    from scripts import social_db
except Exception:  # pragma: no cover - script execution fallback
    import social_db

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "state" / "posts.jsonl"

MIN_AGE_SECS = 3600         # skip posts younger than 1h
MAX_AGE_SECS = 7 * 86400    # stop tracking after 7 days


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(ln) for ln in HISTORY.read_text().splitlines() if ln.strip()]


def save_history(entries: list[dict]) -> None:
    HISTORY.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def tweet_id_from_url(url: str) -> str | None:
    parts = url.rstrip("/").split("/")
    try:
        return parts[parts.index("status") + 1]
    except (ValueError, IndexError):
        return None


def main() -> int:
    history = load_history()
    if not history:
        print("no history")
        return 0

    db = social_db.connect()
    if db:
        social_db.ensure_schema(db)
        social_db.sync_jsonl_history(db, history)
        print("postgres: ledger synced before metrics fetch")

    client = tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )

    now = int(time.time())
    id_to_entry: dict[str, dict] = {}

    for entry in history:
        age = now - entry.get("ts", now)
        if age < MIN_AGE_SECS or age > MAX_AGE_SECS:
            continue
        tid = entry.get("tweet_id") or tweet_id_from_url(entry.get("tweet_url", ""))
        if tid:
            id_to_entry[tid] = entry

    if not id_to_entry:
        print("no posts in tracking window")
        return 0

    print(f"fetching metrics for {len(id_to_entry)} posts")
    updated = 0

    for i in range(0, len(id_to_entry), 100):
        batch = list(id_to_entry.keys())[i:i + 100]
        try:
            resp = client.get_tweets(batch, tweet_fields=["public_metrics"], user_auth=True)
            for tweet in (resp.data or []):
                entry = id_to_entry[str(tweet.id)]
                if tweet.public_metrics:
                    entry["metrics"] = dict(tweet.public_metrics)
                    entry["metrics_ts"] = now
                    if db:
                        social_db.record_engagement(db, entry, entry["metrics"], checked_ts=now)
                    updated += 1
                    m = tweet.public_metrics
                    print(f"  {tweet.id}: imp={m.get('impression_count', '?')} "
                          f"likes={m.get('like_count', '?')} "
                          f"replies={m.get('reply_count', '?')}")
        except Exception as exc:
            print(f"batch fetch error: {exc}", file=sys.stderr)

    if updated:
        save_history(history)
        print(f"updated {updated} posts")
    else:
        print("nothing updated")

    if db:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
