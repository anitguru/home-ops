#!/usr/bin/env python3
"""Shared Postgres persistence for @anitdotguru social automation.

The repo still keeps state/posts.jsonl as an auditable flat-file ledger, but
Wave 3 uses the LAN Postgres heartbeat DB as the queryable/correlation layer.
All functions no-op when PG_DSN is absent so local/dev runs stay simple.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Iterable

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover - optional dependency in non-DB tests
    psycopg2 = None

PLATFORM = "x"
PERSONA = "anitdotguru"


def enabled() -> bool:
    return bool(os.environ.get("PG_DSN")) and psycopg2 is not None


def connect():
    if not enabled():
        return None
    return psycopg2.connect(os.environ["PG_DSN"])


def utc_from_ts(ts: int | float | None):
    if not ts:
        return None
    return dt.datetime.fromtimestamp(float(ts), tz=dt.UTC)


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    p = urllib.parse.urlparse(url.lower().strip())
    return urllib.parse.urlunparse(p._replace(path=p.path.rstrip("/")))


def url_domain(url: str | None) -> str:
    if not url:
        return ""
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def ensure_schema(conn) -> None:
    """Make the existing heartbeat schema Wave-3 capable without destructive migrations."""
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
              id serial PRIMARY KEY,
              platform text NOT NULL,
              persona text NOT NULL,
              post_id text NOT NULL,
              content text,
              posted_at timestamptz,
              url text,
              trending_topic text,
              created_at timestamptz DEFAULT now(),
              UNIQUE(platform, post_id)
            );
            CREATE TABLE IF NOT EXISTS engagement (
              id serial PRIMARY KEY,
              post_id integer REFERENCES posts(id),
              likes integer DEFAULT 0,
              reposts integer DEFAULT 0,
              replies integer DEFAULT 0,
              impressions integer DEFAULT 0,
              checked_at timestamptz DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS interactions (
              id serial PRIMARY KEY,
              platform text NOT NULL,
              persona text NOT NULL,
              type text NOT NULL,
              their_user text,
              their_content text,
              our_response text,
              responded_at timestamptz,
              run_id integer,
              created_at timestamptz DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS heartbeat_runs (
              id serial PRIMARY KEY,
              persona text NOT NULL,
              started_at timestamptz DEFAULT now(),
              finished_at timestamptz,
              reactions_processed integer DEFAULT 0,
              engagements_made integer DEFAULT 0,
              posts_created integer DEFAULT 0,
              errors text[],
              trending_topics text[],
              api_cost_cents integer DEFAULT 0
            );
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS source_url text;
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS source_title text;
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS method text;
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS content_hash text;
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS raw jsonb;
            ALTER TABLE engagement ADD COLUMN IF NOT EXISTS raw jsonb;
            ALTER TABLE interactions ADD COLUMN IF NOT EXISTS their_id text;
            ALTER TABLE interactions ADD COLUMN IF NOT EXISTS related_post_id integer REFERENCES posts(id);
            ALTER TABLE interactions ADD COLUMN IF NOT EXISTS score integer DEFAULT 0;
            ALTER TABLE interactions ADD COLUMN IF NOT EXISTS metadata jsonb;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_interactions_unique_event
              ON interactions(platform, persona, type, their_id)
              WHERE their_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_posts_source_url ON posts(source_url);
            CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(persona, posted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_engagement_post_checked ON engagement(post_id, checked_at DESC);
            """
        )
    conn.commit()


def upsert_post(conn, entry: dict[str, Any]) -> int | None:
    if conn is None:
        return None
    tweet_id = str(entry.get("tweet_id") or entry.get("post_id") or "").strip()
    if not tweet_id:
        return None
    text = entry.get("text") or entry.get("content")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posts (platform, persona, post_id, content, posted_at, url,
                               trending_topic, source_url, source_title, method,
                               content_hash, raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (platform, post_id) DO UPDATE SET
              content = EXCLUDED.content,
              posted_at = COALESCE(posts.posted_at, EXCLUDED.posted_at),
              url = COALESCE(EXCLUDED.url, posts.url),
              trending_topic = COALESCE(EXCLUDED.trending_topic, posts.trending_topic),
              source_url = COALESCE(EXCLUDED.source_url, posts.source_url),
              source_title = COALESCE(EXCLUDED.source_title, posts.source_title),
              method = COALESCE(EXCLUDED.method, posts.method),
              content_hash = COALESCE(EXCLUDED.content_hash, posts.content_hash),
              raw = COALESCE(posts.raw, '{}'::jsonb) || EXCLUDED.raw
            RETURNING id
            """,
            (
                PLATFORM,
                PERSONA,
                tweet_id,
                text,
                utc_from_ts(entry.get("ts")),
                entry.get("tweet_url") or entry.get("url"),
                entry.get("source_title"),
                normalize_url(entry.get("source_url")),
                entry.get("source_title"),
                entry.get("method"),
                content_hash(text),
                json.dumps(entry),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def sync_jsonl_history(conn, history: Iterable[dict[str, Any]]) -> int:
    if conn is None:
        return 0
    ensure_schema(conn)
    count = 0
    for entry in history:
        if upsert_post(conn, entry):
            count += 1
        if entry.get("metrics"):
            record_engagement(conn, entry, entry["metrics"], checked_ts=entry.get("metrics_ts"))
    return count


def load_post_history(conn, limit: int = 200) -> list[dict[str, Any]]:
    if conn is None:
        return []
    ensure_schema(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.*, e.likes, e.reposts, e.replies, e.impressions, e.checked_at
            FROM posts p
            LEFT JOIN LATERAL (
              SELECT * FROM engagement e
              WHERE e.post_id = p.id
              ORDER BY e.checked_at DESC
              LIMIT 1
            ) e ON true
            WHERE p.platform=%s AND p.persona=%s
            ORDER BY COALESCE(p.posted_at, p.created_at) DESC
            LIMIT %s
            """,
            (PLATFORM, PERSONA, limit),
        )
        rows = cur.fetchall()
    history = []
    for row in rows:
        raw = dict(row.get("raw") or {})
        entry = {
            **raw,
            "tweet_id": row["post_id"],
            "tweet_url": row.get("url"),
            "source_url": row.get("source_url"),
            "source_title": row.get("source_title") or row.get("trending_topic"),
            "text": row.get("content"),
            "method": row.get("method") or raw.get("method"),
            "ts": int(row["posted_at"].timestamp()) if row.get("posted_at") else raw.get("ts", 0),
        }
        if row.get("checked_at"):
            entry["metrics"] = {
                "like_count": row.get("likes") or 0,
                "retweet_count": row.get("reposts") or 0,
                "reply_count": row.get("replies") or 0,
                "impression_count": row.get("impressions") or 0,
            }
            entry["metrics_ts"] = int(row["checked_at"].timestamp())
        history.append(entry)
    return history


def record_engagement(conn, entry: dict[str, Any], metrics: dict[str, Any], checked_ts: int | None = None) -> None:
    if conn is None:
        return
    post_pk = upsert_post(conn, entry)
    if not post_pk:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO engagement (post_id, likes, reposts, replies, impressions, checked_at, raw)
            VALUES (%s,%s,%s,%s,%s,COALESCE(%s, now()),%s)
            """,
            (
                post_pk,
                metrics.get("like_count", metrics.get("likes", 0)) or 0,
                metrics.get("retweet_count", metrics.get("reposts", 0)) or 0,
                metrics.get("reply_count", metrics.get("replies", 0)) or 0,
                metrics.get("impression_count", metrics.get("impressions", 0)) or 0,
                utc_from_ts(checked_ts),
                json.dumps(metrics),
            ),
        )
    conn.commit()


def find_post_by_external_id(conn, external_id: str | None) -> dict[str, Any] | None:
    if conn is None or not external_id:
        return None
    ensure_schema(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM posts WHERE platform=%s AND persona=%s AND post_id=%s LIMIT 1",
            (PLATFORM, PERSONA, str(external_id)),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def interaction_exists(conn, type_: str, their_id: str) -> bool:
    if conn is None:
        return False
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM interactions WHERE platform=%s AND persona=%s AND type=%s AND their_id=%s LIMIT 1",
            (PLATFORM, PERSONA, type_, str(their_id)),
        )
        return cur.fetchone() is not None


def log_interaction(
    conn,
    type_: str,
    their_id: str,
    their_user: str,
    their_content: str,
    our_response: str,
    *,
    related_post_pk: int | None = None,
    score: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    if conn is None:
        return
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO interactions (platform, persona, type, their_id, their_user,
                                      their_content, our_response, responded_at,
                                      related_post_id, score, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s)
            ON CONFLICT (platform, persona, type, their_id) WHERE their_id IS NOT NULL DO NOTHING
            """,
            (
                PLATFORM,
                PERSONA,
                type_,
                str(their_id),
                their_user,
                their_content,
                our_response,
                related_post_pk,
                score,
                json.dumps(metadata or {}),
            ),
        )
    conn.commit()


def top_context(conn, limit: int = 4) -> list[dict[str, Any]]:
    """Return compact high-performing post context for correlation prompts."""
    if conn is None:
        return []
    ensure_schema(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.post_id, p.content, p.source_title, p.source_url,
                   COALESCE(e.likes,0) likes, COALESCE(e.replies,0) replies,
                   COALESCE(e.reposts,0) reposts, COALESCE(e.impressions,0) impressions,
                   (COALESCE(e.likes,0)*3 + COALESCE(e.replies,0)*4 + COALESCE(e.reposts,0)*5) score
            FROM posts p
            LEFT JOIN LATERAL (
              SELECT * FROM engagement e WHERE e.post_id=p.id ORDER BY e.checked_at DESC LIMIT 1
            ) e ON true
            WHERE p.platform=%s AND p.persona=%s
            ORDER BY score DESC, p.posted_at DESC NULLS LAST
            LIMIT %s
            """,
            (PLATFORM, PERSONA, limit),
        )
        return [dict(r) for r in cur.fetchall()]
