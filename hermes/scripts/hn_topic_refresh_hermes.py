#!/usr/bin/env python3
"""Refresh HN trending-topic rows through Hermes one-shot LLM extraction.

This script intentionally does not call provider SDKs or provider-specific CLIs.
It fetches a small batch of Hacker News stories/comments, asks a Hermes profile
for strict JSON topic extraction, and optionally writes rows compatible with the
existing CocoIndex topic table consumed by ``cocoindex_rank.py``.

Safe defaults:
- dry-run unless --write is passed
- default Hermes profile/provider/model are configurable
- direct Anthropic/Claude env vars are stripped by scripts.hermes_llm
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

try:
    from scripts.hermes_llm import run_hermes_prompt, strip_code_fences
except Exception:  # pragma: no cover - direct script execution fallback
    from hermes_llm import run_hermes_prompt, strip_code_fences

ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM_URL = "https://hn.algolia.com/api/v1/items/{item_id}"
DEFAULT_TABLE = "hntrendingtopics__hn_topics"


@dataclasses.dataclass(frozen=True)
class HnItem:
    message_id: str
    thread_id: str
    content_type: str
    title: str
    text: str
    url: str
    created_at: str

    def llm_text(self, max_chars: int = 4000) -> str:
        parts = [f"Title: {self.title.strip()}"]
        if self.url:
            parts.append(f"URL: {self.url.strip()}")
        if self.text:
            parts.append("Text:\n" + self.text.strip())
        return "\n\n".join(parts)[:max_chars]


def _fetch_json(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "anitguru-hn-topic-refresh/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _created_at(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    return value.replace("+00:00", "Z")


def _walk_comments(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for child in node.get("children") or []:
        yield child
        yield from _walk_comments(child)


def fetch_hn_items(limit: int = 8, comments_per_story: int = 2) -> list[HnItem]:
    data = _fetch_json(ALGOLIA_SEARCH_URL, {"tags": "front_page", "hitsPerPage": limit})
    items: list[HnItem] = []
    for hit in data.get("hits", []):
        thread_id = str(hit.get("objectID") or "")
        if not thread_id:
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={thread_id}"
        title = hit.get("title") or hit.get("story_title") or "Untitled"
        text = hit.get("story_text") or hit.get("comment_text") or ""
        items.append(HnItem(
            message_id=thread_id,
            thread_id=thread_id,
            content_type="thread",
            title=title,
            text=text,
            url=url,
            created_at=_created_at(hit.get("created_at")),
        ))
        if comments_per_story <= 0:
            continue
        try:
            detail = _fetch_json(ALGOLIA_ITEM_URL.format(item_id=thread_id))
        except Exception as exc:
            print(f"[hn-topic-refresh] Could not fetch comments for {thread_id}: {exc}", file=sys.stderr)
            continue
        count = 0
        for comment in _walk_comments(detail):
            text = comment.get("text") or ""
            cid = comment.get("id")
            if not cid or not text.strip():
                continue
            items.append(HnItem(
                message_id=str(cid),
                thread_id=thread_id,
                content_type="comment",
                title=title,
                text=text,
                url=f"https://news.ycombinator.com/item?id={thread_id}",
                created_at=_created_at(comment.get("created_at")),
            ))
            count += 1
            if count >= comments_per_story:
                break
    return items


def build_prompt(item: HnItem, max_topics: int = 8) -> str:
    return f"""Extract canonical technology/business topics from this Hacker News item.

Return ONLY a JSON array. No prose. No markdown.
Each item must be an object with exactly this shape: {{"topic":"Canonical Topic Name"}}.
Rules:
- Return at most {max_topics} topics.
- Prefer product names, technologies, model names, companies, protocols, people, and domains.
- Use canonical names: "Model Context Protocol" not "MCP" unless the acronym is the canonical name.
- Do not include generic topics like "technology", "startup", "AI", or "news" unless they are part of a specific named concept.
- Do not invent topics not supported by the text.

HN item:
{item.llm_text()}
"""


def extract_json_array(text: str) -> list[Any]:
    raw = strip_code_fences(text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("Hermes topic extraction returned JSON, but not an array")
    return parsed


def _canonical_topic(topic: str) -> str:
    cleaned = re.sub(r"\s+", " ", topic.strip())
    if not cleaned:
        return ""
    overrides = {
        "qwen": "Qwen",
        "openai": "OpenAI",
        "gpt": "GPT",
        "mcp": "Model Context Protocol",
    }
    return overrides.get(cleaned.casefold(), cleaned[:120])


def normalize_topics(raw_topics: list[Any], limit: int = 8) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for raw in raw_topics:
        if isinstance(raw, dict):
            topic = raw.get("topic", "")
        elif isinstance(raw, str):
            topic = raw
        else:
            continue
        topic = _canonical_topic(str(topic))
        if not topic:
            continue
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic)
        if len(topics) >= limit:
            break
    return topics


def extract_topics_for_item(
    item: HnItem,
    *,
    runner: Callable[..., str] = run_hermes_prompt,
    profile: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_topics: int = 8,
    timeout: int = 300,
) -> list[str]:
    output = runner(
        build_prompt(item, max_topics=max_topics),
        profile=profile,
        provider=provider,
        model=model,
        timeout=timeout,
        source="hn-topic-refresh",
    )
    return normalize_topics(extract_json_array(output), limit=max_topics)


def rows_for_item(item: HnItem, topics: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "topic": topic,
            "message_id": item.message_id,
            "thread_id": item.thread_id,
            "content_type": item.content_type,
            "created_at": item.created_at,
        }
        for topic in topics
    ]


def write_topic_rows(rows: list[dict[str, Any]], database_url: str, table: str = DEFAULT_TABLE) -> None:
    import psycopg2
    from psycopg2 import sql

    if not rows:
        return
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    topic TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at TIMESTAMPTZ,
                    PRIMARY KEY (topic, message_id)
                )
            """).format(sql.Identifier(table)))
            for row in rows:
                cur.execute(sql.SQL("""
                    INSERT INTO {} (topic, message_id, thread_id, content_type, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (topic, message_id) DO UPDATE SET
                        thread_id = EXCLUDED.thread_id,
                        content_type = EXCLUDED.content_type,
                        created_at = EXCLUDED.created_at
                """).format(sql.Identifier(table)), (
                    row["topic"],
                    row["message_id"],
                    row["thread_id"],
                    row["content_type"],
                    row["created_at"],
                ))


def refresh_topics(
    *,
    limit: int,
    comments_per_story: int,
    profile: str | None,
    provider: str | None,
    model: str | None,
    max_topics: int,
    write: bool,
    database_url: str | None,
    table: str,
) -> list[dict[str, Any]]:
    items = fetch_hn_items(limit=limit, comments_per_story=comments_per_story)
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(items, 1):
        print(f"[{idx}/{len(items)}] {item.content_type}:{item.message_id} {item.title[:70]}")
        try:
            topics = extract_topics_for_item(
                item,
                profile=profile,
                provider=provider,
                model=model,
                max_topics=max_topics,
            )
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue
        print(f"  topics: {', '.join(topics) or 'none'}")
        rows.extend(rows_for_item(item, topics))
    if write:
        if not database_url:
            raise RuntimeError("--write requires COCOINDEX_DATABASE_URL or --database-url")
        write_topic_rows(rows, database_url, table=table)
        print(f"[hn-topic-refresh] wrote {len(rows)} topic rows to {table}")
    else:
        print(f"[hn-topic-refresh] dry run; {len(rows)} topic rows not written")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh HN topic rows via Hermes one-shot extraction")
    parser.add_argument("--limit", type=int, default=int(os.getenv("HN_TOPIC_LIMIT", "5")), help="HN stories to fetch")
    parser.add_argument("--comments-per-story", type=int, default=int(os.getenv("HN_TOPIC_COMMENTS_PER_STORY", "1")))
    parser.add_argument("--max-topics", type=int, default=int(os.getenv("HN_TOPIC_MAX_TOPICS", "8")))
    parser.add_argument("--profile", default=os.getenv("HN_TOPIC_HERMES_PROFILE", "default"))
    parser.add_argument("--provider", default=os.getenv("HN_TOPIC_HERMES_PROVIDER", "openai-codex"))
    parser.add_argument("--model", default=os.getenv("HN_TOPIC_HERMES_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--database-url", default=os.getenv("COCOINDEX_DATABASE_URL"))
    parser.add_argument("--table", default=os.getenv("HN_TOPIC_TABLE", DEFAULT_TABLE))
    parser.add_argument("--write", action="store_true", help="Write rows to Postgres; default is dry-run")
    parser.add_argument("--json", action="store_true", help="Print extracted rows as JSON after the summary")
    args = parser.parse_args()

    rows = refresh_topics(
        limit=args.limit,
        comments_per_story=args.comments_per_story,
        profile=args.profile,
        provider=args.provider,
        model=args.model,
        max_topics=args.max_topics,
        write=args.write,
        database_url=args.database_url,
        table=args.table,
    )
    if args.json:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
