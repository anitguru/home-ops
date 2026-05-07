#!/usr/bin/env python3
"""
Wave-2 poster for @anitdotguru.

Pipeline: Tavily trending search -> optional Hermes one-shot drafts opinionated tweet -> tweepy post -> state/posts.jsonl.
Falls back to deterministic title+link if the LLM call fails or POST_USE_LLM=0.
"""
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import urllib.parse

import requests
import tweepy

try:
    from scripts import social_db
except Exception:  # pragma: no cover - script execution fallback
    import social_db

HOME_OPS_HERMES_SCRIPTS = Path(os.environ.get(
    "HOME_OPS_HERMES_SCRIPTS",
    "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
))
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))
from hermes_llm import run_hermes_prompt

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "state" / "posts.jsonl"

RECENT_DOMAIN_WINDOW = 5  # block same domain if it appeared in last N posts

QUERY = "trending AI builder tools agents automation no-code 2026"
TAVILY_URL = "https://api.tavily.com/search"
MAX_LEN = 280
URL_COST = 24  # X counts any URL as 23 chars + 1 space


def tavily_search() -> dict:
    r = requests.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {os.environ['TAVILY_API_TOKEN']}"},
        json={
            "query": QUERY,
            "search_depth": "advanced",
            "time_range": "week",
            "max_results": 7,
            "include_answer": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(line) for line in HISTORY.read_text().splitlines() if line.strip()]


def normalize_url(url: str) -> str:
    p = urllib.parse.urlparse(url.lower().strip())
    return urllib.parse.urlunparse(p._replace(path=p.path.rstrip("/")))


def url_domain(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def already_posted(url: str, history: list[dict]) -> bool:
    norm = normalize_url(url)
    return any(normalize_url(h.get("source_url", "")) == norm for h in history)


def recent_domain_used(url: str, history: list[dict]) -> bool:
    domain = url_domain(url)
    recent = [h for h in history if h.get("source_url")]
    recent_sorted = sorted(recent, key=lambda h: h.get("ts", 0), reverse=True)
    return any(url_domain(h["source_url"]) == domain for h in recent_sorted[:RECENT_DOMAIN_WINDOW])


def pick_signal(data: dict, history: list[dict]) -> dict | None:
    for r in data.get("results", []):
        if not already_posted(r["url"], history) and not recent_domain_used(r["url"], history):
            return r
    # fallback: relax domain window if nothing passes
    for r in data.get("results", []):
        if not already_posted(r["url"], history):
            return r
    return None


def top_performers(history: list[dict], n: int = 3) -> list[dict]:
    scored = [
        (e["metrics"].get("like_count", 0) * 3 + e["metrics"].get("reply_count", 0) * 2
         + e["metrics"].get("retweet_count", 0) * 5, e)
        for e in history
        if e.get("metrics") and e.get("method") == "llm"
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for score, e in scored[:n] if score > 0]


def craft_tweet_llm(signal: dict, answer: str, history: list[dict] | None = None) -> str | None:
    """Optionally use a Hermes one-shot profile to write a tweet in @anitdotguru's voice."""
    if os.getenv("POST_USE_LLM", "1").lower() in {"0", "false", "no"}:
        return None

    performers_block = ""
    if history:
        top = top_performers(history)
        if top:
            examples = "\n".join(f'- "{e["text"].rsplit(" http", 1)[0]}"' for e in top)
            performers_block = f"\n\nHigh-engagement examples from your past posts:\n{examples}\nMatch the tone and specificity of these."

    prompt = (
        "You are @anitdotguru — a pragmatic technical expert who builds with AI, "
        "homelabs, and self-hosted tools. Conversational, never corporate. You share "
        "what you learned the hard way. No emojis, no thread format, no quotes around output.\n\n"
        f"Write a single tweet comment about this article. Do NOT include the URL — I'll append it.\n\n"
        f"Title: {signal['title']}\n"
        f"Snippet: {signal.get('content', '')[:500]}\n"
        f"Broader trend: {answer[:300]}"
        f"{performers_block}\n\n"
        f"Add your own angle or takeaway — don't restate the title. "
        f"Be specific and opinionated. One or two sentences max.\n\n"
        f"After the tweet body, on a new line write: HASHTAGS: #tag1 #tag2\n"
        f"Pick 1-2 specific contextual tags (e.g. #agentdev, #homelab, "
        f"#selfhosted, #llm, #k8s, #mcp, #rag). No generic tags like #AI or #tech."
    )

    try:
        raw = run_hermes_prompt(prompt, timeout=240, source="post-draft").strip()
    except Exception as exc:
        print(f"Hermes draft failed: {exc}")
        return None

    # Parse optional HASHTAGS line
    hashtag_suffix = ""
    if "\nHASHTAGS:" in raw:
        body_part, tag_part = raw.rsplit("\nHASHTAGS:", 1)
        tags = [t for t in tag_part.strip().split() if t.startswith("#")][:2]
        if tags:
            hashtag_suffix = " " + " ".join(tags)
        raw = body_part

    body = raw.strip().strip('"').strip("'")
    body_budget = MAX_LEN - URL_COST - len(hashtag_suffix)
    if len(body) > body_budget:
        body = textwrap.shorten(body, width=body_budget, placeholder="…")

    return f"{body} {signal['url']}{hashtag_suffix}"


def craft_tweet_fallback(signal: dict) -> str:
    title = signal["title"].strip().rstrip(".")
    body_budget = MAX_LEN - URL_COST
    body = textwrap.shorten(title, width=body_budget, placeholder="…")
    return f"{body} {signal['url']}"


def post(text: str) -> str:
    client = tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    resp = client.create_tweet(text=text)
    tid = resp.data["id"]
    return f"https://x.com/anitdotguru/status/{tid}"


def append_history(entry: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> int:
    history = load_history()
    db = social_db.connect()
    if db:
        social_db.ensure_schema(db)
        synced = social_db.sync_jsonl_history(db, history)
        db_history = social_db.load_post_history(db)
        # Keep jsonl as the ledger, but let Postgres enrich dedupe and performance context.
        seen = {h.get("tweet_id") for h in history if h.get("tweet_id")}
        history.extend([h for h in db_history if h.get("tweet_id") not in seen])
        print(f"postgres: synced {synced} ledger posts, loaded {len(db_history)} db posts")
    print(f"history: {len(history)} prior posts")

    data = tavily_search()
    signal = pick_signal(data, history)
    if not signal:
        print("no fresh signal in Tavily results — skipping")
        return 0

    answer = data.get("answer", "")
    text = craft_tweet_llm(signal, answer, history)
    method = "llm"
    if not text:
        text = craft_tweet_fallback(signal)
        method = "fallback"

    print(f"drafted [{method}] ({len(text)} chars): {text}")

    tweet_url = post(text)
    tweet_id = tweet_url.rstrip("/").split("/")[-1]
    print(f"posted: {tweet_url}")

    entry = {
        "ts": int(time.time()),
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "source_url": signal["url"],
        "source_title": signal["title"],
        "text": text,
        "method": method,
    }
    append_history(entry)
    if db:
        social_db.upsert_post(db, entry)
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
