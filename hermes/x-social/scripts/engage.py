#!/usr/bin/env python3
"""
Wave 3 engagement loop for @anitdotguru.

Polls X mentions -> scores actionability -> auto-likes genuine engagement ->
uses LAN Postgres for dedupe/correlation -> optionally routes reply drafting
through a Hermes one-shot profile when the X self-serve rules allow it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tweepy

try:
    from scripts import social_db, state_paths
except Exception:  # pragma: no cover - script execution fallback
    import social_db
    import state_paths

HOME_OPS_HERMES_SCRIPTS = Path(os.environ.get(
    "HOME_OPS_HERMES_SCRIPTS",
    "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
))
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))
from hermes_llm import run_hermes_prompt

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = state_paths.ENGAGE_CURSOR

MAX_REPLIES_PER_RUN = int(os.environ.get("MAX_REPLIES_PER_RUN", "5"))
MIN_REPLY_SCORE = int(os.environ.get("MIN_REPLY_SCORE", "3"))
PERSONA = social_db.PERSONA
PLATFORM = social_db.PLATFORM

SPAM_SIGNALS = [
    "follow back", "follow me", "giveaway", "free money", "earn $", "click here", "dm me",
    "airdrop", "crypto pump", "telegram group", "whatsapp", "forex",
]
LOW_VALUE_REPLIES = {"thanks", "thank you", "ok", "okk", "cool", "nice", "great", "yes", "no"}
QUESTION_RE = re.compile(r"\?|\b(how|why|what|where|when|which|can you|do you|should i|any tips)\b", re.I)
TECH_RE = re.compile(r"\b(homelab|self-host|selfhost|agent|llm|mcp|rag|postgres|docker|k8s|kubernetes|n8n|automation|workflow|local|infra|server|linux|ai)\b", re.I)


@dataclass
class ActivityRef:
    id: str
    type: str = "replied_to"


@dataclass
class ActivityUser:
    id: str
    username: str


@dataclass
class ActivityMention:
    id: str
    author_id: str
    text: str
    username: str | None = None
    referenced_tweets: list[ActivityRef] = field(default_factory=list)
    public_metrics: dict[str, Any] = field(default_factory=dict)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _tweet_id(tweet: Any) -> str:
    return str(_value(tweet, "id", None) or _value(tweet, "id_str", ""))


def _tweet_text(tweet: Any) -> str:
    return str(_value(tweet, "text", None) or _value(tweet, "full_text", ""))


# ── state cursor ──────────────────────────────────────────────────────────────

def load_cursor() -> str | None:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text()).get("since_id")
    return None


def save_cursor(since_id: str):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"since_id": since_id, "updated_at": int(time.time())}))


# ── twitter client ────────────────────────────────────────────────────────────

def make_client():
    return tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def get_own_user_id(client) -> str:
    resp = client.get_me(user_auth=True)
    return str(resp.data.id)


def x_api_payment_required(exc: Exception) -> bool:
    """Return True when X API rejects a read because the app/tier needs paid access."""
    text = str(exc).lower()
    return "402" in text and "payment required" in text


# ── filtering/scoring ─────────────────────────────────────────────────────────

def stripped_mention_text(tweet_text: str) -> str:
    return re.sub(r"@\w+", "", tweet_text or "").strip()


def is_genuine(tweet_text: str) -> bool:
    text = (tweet_text or "").lower()
    return not any(s in text for s in SPAM_SIGNALS)


def referenced_own_post_id(tweet) -> str | None:
    refs = _value(tweet, "referenced_tweets", None) or []
    for ref in refs:
        if _value(ref, "type") in {"replied_to", "quoted"}:
            return str(_value(ref, "id"))
    return None


def mentions_from_account_activity(
    payload: dict[str, Any],
    own_user_id: str,
    own_username: str = "anitdotguru",
) -> tuple[list[ActivityMention], dict[str, ActivityUser]]:
    """Extract @mentions from an Account Activity API payload.

    Account Activity payloads include all account events. Wave 3 only engages
    with tweet_create_events where someone else mentions the subscribed user.
    """
    mentions: list[ActivityMention] = []
    users: dict[str, ActivityUser] = {}
    own_user_id = str(own_user_id)
    own_username_l = own_username.lower().lstrip("@")

    for tweet in payload.get("tweet_create_events") or []:
        user = tweet.get("user") or {}
        author_id = str(user.get("id_str") or user.get("id") or tweet.get("author_id") or "")
        username = str(user.get("screen_name") or user.get("username") or "unknown")
        if author_id == own_user_id:
            continue

        entities = tweet.get("entities") or {}
        user_mentions = entities.get("user_mentions") or []
        mentions_us = any(
            str(m.get("id_str") or m.get("id") or "") == own_user_id
            or str(m.get("screen_name") or m.get("username") or "").lower().lstrip("@") == own_username_l
            for m in user_mentions
        )
        if not mentions_us:
            continue

        tweet_id = _tweet_id(tweet)
        if not tweet_id:
            continue
        referenced_tweets: list[ActivityRef] = []
        reply_to_id = tweet.get("in_reply_to_status_id_str") or tweet.get("in_reply_to_status_id")
        if reply_to_id:
            referenced_tweets.append(ActivityRef(id=str(reply_to_id), type="replied_to"))
        quoted_id = tweet.get("quoted_status_id_str") or tweet.get("quoted_status_id")
        if quoted_id:
            referenced_tweets.append(ActivityRef(id=str(quoted_id), type="quoted"))

        public_metrics = {
            "like_count": tweet.get("favorite_count", 0) or 0,
            "retweet_count": tweet.get("retweet_count", 0) or 0,
            "reply_count": tweet.get("reply_count", 0) or 0,
            "quote_count": tweet.get("quote_count", 0) or 0,
        }
        mention = ActivityMention(
            id=tweet_id,
            author_id=author_id,
            username=username,
            text=_tweet_text(tweet),
            referenced_tweets=referenced_tweets,
            public_metrics=public_metrics,
        )
        mentions.append(mention)
        users[author_id] = ActivityUser(id=author_id, username=username)

    return mentions, users


def score_mention(tweet_text: str, related_post: dict[str, Any] | None) -> tuple[int, list[str]]:
    """Score whether a mention merits a reply instead of just a like."""
    text = stripped_mention_text(tweet_text)
    lowered = text.lower().strip(" .!…")
    score = 0
    reasons: list[str] = []

    if not is_genuine(tweet_text):
        return -10, ["spam_signal"]
    if related_post:
        score += 2
        reasons.append("linked_to_our_post")
    if QUESTION_RE.search(text):
        score += 3
        reasons.append("question")
    if TECH_RE.search(text):
        score += 2
        reasons.append("technical_context")
    if len(text) >= 60:
        score += 1
        reasons.append("substantive_length")
    if lowered in LOW_VALUE_REPLIES or len(text) < 12:
        score -= 3
        reasons.append("low_value_ack")

    return score, reasons


# ── optional Hermes reply drafter ──────────────────────────────────────────────

def draft_reply(their_text: str, their_username: str, related_post: dict[str, Any] | None, top_posts: list[dict[str, Any]]) -> str | None:
    if os.getenv("ENGAGE_USE_LLM", "1").lower() in {"0", "false", "no"}:
        return None
    try:
        related_block = ""
        if related_post:
            related_block = (
                "\nThey are responding to one of our posts:\n"
                f"Post: {related_post.get('content', '')[:360]}\n"
                f"Source: {related_post.get('source_title') or related_post.get('trending_topic') or ''}\n"
            )

        top_block = ""
        if top_posts:
            top_block = "\nHigh-performing prior angles to keep consistent with:\n" + "\n".join(
                f"- {p.get('content', '')[:180]}" for p in top_posts[:3] if p.get("content")
            )

        prompt = (
            "You are @anitdotguru — pragmatic, technical, direct. "
            "You reply only when someone engaged with you. Keep it short "
            "(1-2 sentences max), conversational, no emojis, no hollow praise. "
            "Do not start with the person's name. Never say 'great point' or 'thanks for sharing'. "
            "If they ask a practical question, give a practical answer.\n\n"
            f"@{their_username} said: \"{their_text}\"\n"
            f"{related_block}{top_block}\n\n"
            f"Write a short reply under 200 chars, not counting @mention. "
            f"Be specific and genuine. Do not include @{their_username} in your reply — it will be prepended. "
            "Output only the reply text."
        )
        return run_hermes_prompt(prompt, timeout=180, source="engage-reply").strip().strip('"')
    except Exception as exc:
        print(f"Hermes reply draft failed: {exc}", file=sys.stderr)
        return None


# ── engagement processing ─────────────────────────────────────────────────────

def process_mentions(
    client,
    conn,
    mentions: list[Any],
    users: dict[Any, Any],
    *,
    top_posts: list[dict[str, Any]] | None = None,
    update_cursor: bool = True,
) -> dict[str, int]:
    newest_id = None
    replies_sent = 0
    likes_sent = 0
    top_posts = top_posts or []

    print(f"found {len(mentions)} mention(s)")

    for tweet in mentions:
        tweet_id = _tweet_id(tweet)
        if newest_id is None:
            newest_id = tweet_id

        author_id = _value(tweet, "author_id")
        author = users.get(author_id) or users.get(str(author_id))
        username = _value(tweet, "username", None) or (_value(author, "username") if author else "unknown")
        text = _tweet_text(tweet)
        related_external_id = referenced_own_post_id(tweet)
        related_post = social_db.find_post_by_external_id(conn, related_external_id)
        related_post_pk = related_post.get("id") if related_post else None
        score, reasons = score_mention(text, related_post)
        metadata = {
            "reasons": reasons,
            "related_external_id": related_external_id,
            "public_metrics": _value(tweet, "public_metrics", {}) or {},
        }

        if is_genuine(text) and not social_db.interaction_exists(conn, "like", tweet_id):
            try:
                client.like(tweet_id, user_auth=True)
                social_db.log_interaction(
                    conn, "like", tweet_id, username, f"tweet:{tweet_id} {text[:240]}", "liked",
                    related_post_pk=related_post_pk, score=score, metadata=metadata,
                )
                likes_sent += 1
                print(f"  liked @{username} score={score} reasons={','.join(reasons) or 'none'}: {text[:80]}")
            except Exception as exc:
                print(f"  like failed for {tweet_id}: {exc}", file=sys.stderr)

        if replies_sent >= MAX_REPLIES_PER_RUN:
            print(f"  reply budget reached ({MAX_REPLIES_PER_RUN}), skipping remaining")
            break
        if social_db.interaction_exists(conn, "reply", tweet_id):
            print(f"  already replied to {tweet_id}, skipping")
            continue
        if score < MIN_REPLY_SCORE:
            print(f"  no reply score={score} reasons={','.join(reasons) or 'none'} @{username}")
            continue

        reply_body = draft_reply(text, username, related_post, top_posts)
        if not reply_body:
            continue

        reply_text = f"@{username} {reply_body}"
        if len(reply_text) > 280:
            reply_text = reply_text[:277] + "…"

        try:
            client.create_tweet(text=reply_text, in_reply_to_tweet_id=tweet_id, user_auth=True)
            social_db.log_interaction(
                conn, "reply", tweet_id, username, f"tweet:{tweet_id} {text[:240]}", reply_text,
                related_post_pk=related_post_pk, score=score, metadata=metadata,
            )
            print(f"  replied to @{username} score={score}: {reply_text[:100]}")
            replies_sent += 1
        except Exception as exc:
            print(f"  reply failed: {exc}", file=sys.stderr)

    if newest_id and update_cursor:
        save_cursor(newest_id)
        print(f"cursor updated to {newest_id}")

    print(f"done — likes={likes_sent}, replies={replies_sent}, cursor={newest_id}")
    return {"likes": likes_sent, "replies": replies_sent, "mentions": len(mentions)}


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    client = make_client()
    conn = social_db.connect()
    if not conn:
        print("PG_DSN is required for Wave 3 correlation/dedupe", file=sys.stderr)
        return 1
    social_db.ensure_schema(conn)

    own_id = get_own_user_id(client)
    since_id = load_cursor()
    top_posts = social_db.top_context(conn)

    print(f"fetching mentions since_id={since_id or 'none'}")

    try:
        resp = client.get_users_mentions(
            id=own_id,
            since_id=since_id,
            max_results=20,
            tweet_fields=["author_id", "text", "referenced_tweets", "created_at", "public_metrics", "context_annotations"],
            expansions=["author_id"],
            user_auth=True,
        )
    except Exception as exc:
        if x_api_payment_required(exc):
            print(
                "mentions fetch skipped: X API returned 402 Payment Required; "
                "check X API billing/tier before expecting engagement actions",
                file=sys.stderr,
            )
            return 0
        print(f"mentions fetch failed: {exc}", file=sys.stderr)
        return 1

    mentions = resp.data or []
    users = {u.id: u for u in (resp.includes.get("users") or [])} if resp.includes else {}
    process_mentions(client, conn, mentions, users, top_posts=top_posts, update_cursor=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
