#!/usr/bin/env python3
"""
CocoIndex HN Trending Topics — story ranker for Guru's Tech Bytes.

Queries a persistent HN topic index in Supabase Postgres and ranks
stories.json by trending topic overlap. The CocoIndex flow definition
is retained for separate index-update runs, but no automated path defaults
to a direct paid LLM provider anymore.

Requires env for topic-index ranking: COCOINDEX_DATABASE_URL
Fallback:    deterministic score/comment ranking if the topic index is unavailable
Usage:       python scripts/cocoindex_rank.py $PODCAST_DIR
"""

import cocoindex
import os
import sys
import json
from datetime import timedelta, datetime
from typing import Any, NamedTuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re
import aiohttp
import dataclasses

from cocoindex.op import (
    NON_EXISTENCE,
    SourceSpec,
    NO_ORDINAL,
    source_connector,
    PartialSourceRow,
    PartialSourceRowData,
)

THREAD_SCORE_WEIGHT = 5
COMMENT_SCORE_WEIGHT = 1
TOPIC_BOOST = 10


class _ThreadKey(NamedTuple):
    thread_id: str


@dataclasses.dataclass
class _Comment:
    id: str
    author: str | None
    text: str | None
    created_at: datetime | None


@dataclasses.dataclass
class _Thread:
    author: str | None
    text: str
    url: str | None
    created_at: datetime | None
    comments: list[_Comment]


@dataclasses.dataclass
class Topic:
    """
    A single topic extracted from text.
    The topic should be a product name, technology, model, person, company, or domain.
    Use canonical forms (e.g. "Large Language Model" not "LLM").
    Capitalize proper nouns and acronyms only.
    """
    topic: str


class HackerNewsSource(SourceSpec):
    tag: str | None = None
    max_results: int = 50


@source_connector(
    spec_cls=HackerNewsSource,
    key_type=_ThreadKey,
    value_type=_Thread,
)
class HackerNewsConnector:
    _spec: HackerNewsSource
    _session: aiohttp.ClientSession

    def __init__(self, spec, session):
        self._spec = spec
        self._session = session

    @staticmethod
    async def create(spec):
        return HackerNewsConnector(spec, aiohttp.ClientSession())

    async def list(self):
        url = "https://hn.algolia.com/api/v1/search_by_date"
        params: dict[str, Any] = {"hitsPerPage": self._spec.max_results}
        if self._spec.tag:
            params["tags"] = self._spec.tag
        async with self._session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            for hit in data.get("hits", []):
                if thread_id := hit.get("objectID"):
                    utime = hit.get("updated_at")
                    ordinal = (
                        int(datetime.fromisoformat(utime).timestamp())
                        if utime else NO_ORDINAL
                    )
                    yield PartialSourceRow(
                        key=_ThreadKey(thread_id=thread_id),
                        data=PartialSourceRowData(ordinal=ordinal),
                    )

    async def get_value(self, key):
        url = f"https://hn.algolia.com/api/v1/items/{key.thread_id}"
        async with self._session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            if not data:
                return PartialSourceRowData(value=NON_EXISTENCE, ordinal=NO_ORDINAL)
            return PartialSourceRowData(value=_parse_thread(data))

    def provides_ordinal(self):
        return True


def _parse_thread(data: dict[str, Any]) -> _Thread:
    comments: list[_Comment] = []

    def _walk(parent: dict[str, Any]) -> None:
        for child in (parent.get("children") or []):
            if cid := child.get("id"):
                ct = child.get("created_at")
                comments.append(_Comment(
                    id=str(cid),
                    author=child.get("author", ""),
                    text=child.get("text", ""),
                    created_at=datetime.fromisoformat(ct) if ct else None,
                ))
            _walk(child)

    _walk(data)
    ct = data.get("created_at")
    text = data.get("title", "")
    if extra := data.get("text"):
        text += "\n\n" + extra
    return _Thread(
        author=data.get("author"),
        text=text,
        url=data.get("url"),
        created_at=datetime.fromisoformat(ct) if ct else None,
        comments=comments,
    )


def _llm_spec_from_env() -> cocoindex.LlmSpec:
    """Build CocoIndex LLM spec without hard-coding Claude/Anthropic.

    The old default used Anthropic directly. Keep this flow configurable for
    explicit index-update runs, but require callers to choose a non-Anthropic
    provider/model via environment instead of silently spending Claude credits.
    """
    api_type_name = os.environ.get("COCOINDEX_LLM_API_TYPE")
    model = os.environ.get("COCOINDEX_LLM_MODEL")
    if not api_type_name or not model:
        raise RuntimeError(
            "Set COCOINDEX_LLM_API_TYPE and COCOINDEX_LLM_MODEL before running "
            "the HNTrendingTopics CocoIndex flow. Direct Anthropic defaults were removed."
        )
    if api_type_name.upper() == "ANTHROPIC" or "claude" in model.lower():
        raise RuntimeError("Claude/Anthropic CocoIndex runs are disabled for cost control")
    return cocoindex.LlmSpec(
        api_type=getattr(cocoindex.LlmApiType, api_type_name.upper()),
        model=model,
    )


@cocoindex.flow_def(name="HNTrendingTopics")
def hn_topics_flow(
    flow_builder: cocoindex.FlowBuilder,
    data_scope: cocoindex.DataScope,
) -> None:
    data_scope["threads"] = flow_builder.add_source(
        HackerNewsSource(tag="story", max_results=50),
        refresh_interval=timedelta(hours=6),
    )

    msg_idx = data_scope.add_collector()
    topic_idx = data_scope.add_collector()

    with data_scope["threads"].row() as thread:
        thread["topics"] = thread["text"].transform(
            cocoindex.functions.ExtractByLlm(
                llm_spec=_llm_spec_from_env(), output_type=list[Topic],
            )
        )

        msg_idx.collect(
            id=thread["thread_id"], thread_id=thread["thread_id"],
            content_type="thread", author=thread["author"],
            text=thread["text"], url=thread["url"],
            created_at=thread["created_at"],
        )

        with thread["topics"].row() as t:
            topic_idx.collect(
                message_id=thread["thread_id"], thread_id=thread["thread_id"],
                topic=t["topic"], content_type="thread",
                created_at=thread["created_at"],
            )

        with thread["comments"].row() as comment:
            comment["topics"] = comment["text"].transform(
                cocoindex.functions.ExtractByLlm(
                    llm_spec=_llm_spec_from_env(), output_type=list[Topic],
                )
            )

            msg_idx.collect(
                id=comment["id"], thread_id=thread["thread_id"],
                content_type="comment", author=comment["author"],
                text=comment["text"], url="",
                created_at=comment["created_at"],
            )

            with comment["topics"].row() as t:
                topic_idx.collect(
                    message_id=comment["id"], thread_id=thread["thread_id"],
                    topic=t["topic"], content_type="comment",
                    created_at=comment["created_at"],
                )

    msg_idx.export(
        "hn_messages", cocoindex.targets.Postgres(),
        primary_key_fields=["id"],
    )
    topic_idx.export(
        "hn_topics", cocoindex.targets.Postgres(),
        primary_key_fields=["topic", "message_id"],
    )


TOPICS_TABLE = "hntrendingtopics__hn_topics"
RECENT_DUPLICATE_PENALTY = 100_000


def _score_value(story: dict[str, Any], key: str) -> float:
    try:
        return float(story.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    path = parts.path.rstrip("/") or "/"
    query = ""
    if parts.netloc.lower() == "news.ycombinator.com" and path == "/item":
        hn_id = dict(parse_qsl(parts.query)).get("id")
        if hn_id:
            query = urlencode({"id": hn_id})
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or None


def story_identity_keys(story: dict[str, Any]) -> list[str]:
    """Return stable duplicate-detection keys for an HN story.

    URLs catch exact repeats. HN URLs catch reposted source URLs attached to the
    same HN item. Titles catch cases where the article moves or query strings
    differ but the same story keeps surfacing day after day.
    """
    keys: list[str] = []
    for field in ("url", "hn_url", "hnUrl"):
        if normalized := _normalize_url(story.get(field)):
            keys.append(f"url:{normalized}")
    if normalized_title := _normalize_title(story.get("title")):
        keys.append(f"title:{normalized_title}")
    return sorted(set(keys))


def apply_recent_story_penalties(
    stories: list[dict[str, Any]],
    recent_keys: set[str],
    penalty: float = RECENT_DUPLICATE_PENALTY,
) -> None:
    """Mark and heavily down-rank stories already used in recent episodes."""
    for story in stories:
        matches = sorted(set(story_identity_keys(story)) & recent_keys)
        story["is_recent_duplicate"] = bool(matches)
        story["duplicate_matches"] = matches
        if matches:
            story["combined_score"] = _score_value(story, "combined_score") - penalty


def _connect_postgres(dsn: str):
    try:
        import psycopg
        return psycopg.connect(dsn)
    except ModuleNotFoundError:
        import psycopg2
        return psycopg2.connect(dsn)


def _episode_date_from_context(podcast_dir: str) -> str | None:
    metadata_path = os.path.join(podcast_dir, "metadata.json")
    try:
        with open(metadata_path) as f:
            if date := json.load(f).get("date"):
                return str(date)
    except Exception:
        pass
    if today := os.environ.get("TODAY"):
        return today
    basename = os.path.basename(os.path.abspath(podcast_dir))
    match = re.search(r"(\d{4}-\d{2}-\d{2})", basename)
    return match.group(1) if match else None


def load_recent_podcast_story_keys(
    current_date: str | None = None,
    limit: int = 45,
) -> set[str]:
    """Load recently used podcast story identities from podcast_episodes.

    Best effort by design: ranking still works if the DB/table is unavailable,
    but logs that duplicate protection could not be applied.
    """
    dsn = os.environ.get("COCOINDEX_DATABASE_URL")
    if not dsn:
        return set()

    where = "WHERE stories IS NOT NULL"
    params: tuple[Any, ...] = (limit,)
    if current_date:
        where += " AND date < %s"
        params = (current_date, limit)

    keys: set[str] = set()
    with _connect_postgres(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT stories
                FROM podcast_episodes
                {where}
                ORDER BY date DESC
                LIMIT %s
                """,
                params,
            )
            for (stories_json,) in cur.fetchall():
                if isinstance(stories_json, str):
                    stories_json = json.loads(stories_json)
                if not isinstance(stories_json, list):
                    continue
                for story in stories_json:
                    if isinstance(story, dict):
                        keys.update(story_identity_keys(story))
    return keys


def rank_stories_deterministically(stories: list[dict[str, Any]], recent_keys: set[str] | None = None) -> None:
    """No-LLM fallback used when the persisted topic index is unavailable."""
    for story in stories:
        story["topic_score"] = 0
        story["matched_topics"] = []
        story["combined_score"] = _score_value(story, "score") + (_score_value(story, "comments") * 0.5)
    apply_recent_story_penalties(stories, recent_keys or set())
    stories.sort(key=lambda s: s["combined_score"], reverse=True)


def _story_selection_signals(story: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    matched_topics = [str(t) for t in story.get("matched_topics") or []]
    if matched_topics:
        signals.append(f"matched trending topics: {', '.join(matched_topics)}")
    signals.append(f"HN score: {_score_value(story, 'score'):g}")
    if story.get("is_recent_duplicate"):
        signals.append("recently covered duplicate")
    else:
        signals.append("not recently covered")
    return signals


def build_cocoindex_proof(
    *,
    trending: list[dict[str, Any]],
    recent_story_keys: set[str],
    stories: list[dict[str, Any]],
    topic_index_error: str | None = None,
) -> dict[str, Any]:
    """Summarize why CocoIndex added value beyond duplicate checks."""
    used_topic_index = bool(trending)
    cocoindex_value = ["recent-episode duplicate suppression", "story-level ranking rationale"]
    if used_topic_index:
        cocoindex_value.insert(0, "semantic/topic-aware story ranking")

    proof: dict[str, Any] = {
        "ranking_mode": "topic-index" if used_topic_index else "deterministic-fallback",
        "used_topic_index": used_topic_index,
        "top_trending_topics": [str(t.get("topic", "")) for t in trending[:10] if t.get("topic")],
        "recent_story_keys_loaded": len(recent_story_keys),
        "cocoindex_value": cocoindex_value,
        "top_ranked_stories": [
            {
                "title": story.get("title", ""),
                "combined_score": _score_value(story, "combined_score"),
                "hn_score": _score_value(story, "score"),
                "topic_score": _score_value(story, "topic_score"),
                "matched_topics": list(story.get("matched_topics") or []),
                "is_recent_duplicate": bool(story.get("is_recent_duplicate")),
                "selection_signals": _story_selection_signals(story),
            }
            for story in stories[:5]
        ],
    }
    if topic_index_error:
        proof["topic_index_error"] = topic_index_error
    return proof


def write_cocoindex_proof(
    podcast_dir: str,
    *,
    trending: list[dict[str, Any]],
    recent_story_keys: set[str],
    stories: list[dict[str, Any]],
    topic_index_error: str | None = None,
) -> str:
    proof_path = os.path.join(podcast_dir, "cocoindex-proof.json")
    proof = build_cocoindex_proof(
        trending=trending,
        recent_story_keys=recent_story_keys,
        stories=stories,
        topic_index_error=topic_index_error,
    )
    with open(proof_path, "w") as f:
        json.dump(proof, f, indent=2)
    return proof_path


def get_trending_topics(limit: int = 50) -> list[dict[str, Any]]:
    import psycopg
    with psycopg.connect(os.environ["COCOINDEX_DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT topic,
                       SUM(CASE WHEN content_type = 'thread'
                           THEN {THREAD_SCORE_WEIGHT}
                           ELSE {COMMENT_SCORE_WEIGHT} END) AS score,
                       MAX(created_at) AS latest
                FROM {TOPICS_TABLE}
                GROUP BY topic
                ORDER BY score DESC, latest DESC
                LIMIT %s
            """, (limit,))
            return [
                {"topic": r[0], "score": r[1],
                 "latest": r[2].isoformat() if r[2] else ""}
                for r in cur.fetchall()
            ]


def rank_stories(podcast_dir: str) -> None:
    stories_path = os.path.join(podcast_dir, "stories.json")
    output_path = os.path.join(podcast_dir, "ranked-stories.json")

    with open(stories_path) as f:
        stories = json.load(f)

    current_date = _episode_date_from_context(podcast_dir)
    try:
        recent_story_keys = load_recent_podcast_story_keys(current_date=current_date)
        if recent_story_keys:
            print(f"[cocoindex] Loaded {len(recent_story_keys)} recent podcast story keys for dedupe")
    except Exception as exc:
        print(f"[cocoindex] Podcast story dedupe unavailable: {exc}", file=sys.stderr)
        recent_story_keys = set()

    topic_index_error = None
    try:
        trending = get_trending_topics(limit=50)
    except Exception as exc:
        topic_index_error = str(exc)
        print(f"[cocoindex] Topic index unavailable; using deterministic score/comment ranking: {exc}", file=sys.stderr)
        trending = []

    if not trending:
        rank_stories_deterministically(stories, recent_story_keys)
        with open(output_path, "w") as f:
            json.dump(stories, f, indent=2)
        proof_path = write_cocoindex_proof(
            podcast_dir,
            trending=trending,
            recent_story_keys=recent_story_keys,
            stories=stories,
            topic_index_error=topic_index_error or "topic index returned no topics",
        )
        print(f"[cocoindex] Ranked {len(stories)} stories deterministically -> {output_path}")
        print(f"[cocoindex] Proof: {proof_path}")
        for s in stories[:5]:
            duplicate = " recent-duplicate" if s.get("is_recent_duplicate") else ""
            print(f"  [{s['combined_score']:>8.1f}] {s['title'][:60]}  (score/comments fallback{duplicate})")
        return

    topic_scores = {t["topic"].lower(): t["score"] for t in trending}

    for story in stories:
        title_lower = story["title"].lower()
        relevance = 0
        matched = []
        for topic, score in topic_scores.items():
            if topic in title_lower:
                relevance += score
                matched.append(topic)
        story["topic_score"] = relevance
        story["matched_topics"] = matched
        story["combined_score"] = story["score"] + relevance * TOPIC_BOOST

    apply_recent_story_penalties(stories, recent_story_keys)
    stories.sort(key=lambda s: s["combined_score"], reverse=True)

    with open(output_path, "w") as f:
        json.dump(stories, f, indent=2)
    proof_path = write_cocoindex_proof(
        podcast_dir,
        trending=trending,
        recent_story_keys=recent_story_keys,
        stories=stories,
    )

    print(f"[cocoindex] Ranked {len(stories)} stories -> {output_path}")
    print(f"[cocoindex] Top trending: {', '.join(t['topic'] for t in trending[:10])}")
    print(f"[cocoindex] Proof: {proof_path}")
    for s in stories[:5]:
        topics = ", ".join(s["matched_topics"]) or "none"
        print(f"  [{s['combined_score']:>6}] {s['title'][:60]}  ({topics})")


def main() -> None:
    podcast_dir = (
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("PODCAST_DIR", "/tmp/podcast")
    )
    stories_path = os.path.join(podcast_dir, "stories.json")

    if not os.path.exists(stories_path):
        print(
            f"ERROR: {stories_path} not found -- run morning-briefing.sh first",
            file=sys.stderr,
        )
        sys.exit(1)

    print("[cocoindex] Ranking stories from topic index...")
    rank_stories(podcast_dir)


if __name__ == "__main__":
    main()
