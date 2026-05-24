#!/usr/bin/env python3
"""Weekly @anitdotguru X growth audit.

Read-only for X: it analyzes the local post ledger/metrics, asks Grok for
strategy feedback through a minimal-tool Hermes xposting one-shot, appends the
report to the Obsidian wiki, and optionally tunes Hermes cron frequencies using
simple deterministic guardrails.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import state_paths
except Exception:  # pragma: no cover - script execution fallback
    import state_paths

HOME_OPS_HERMES_SCRIPTS = Path(os.environ.get(
    "HOME_OPS_HERMES_SCRIPTS",
    "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
))
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))
from hermes_llm import run_hermes_prompt

VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "/Users/sva/Documents/Dropbox/Obsidian/AnITGuru"))
WIKI = VAULT / "40-wiki"
REPORT_PAGE = WIKI / "queries" / "x-growth-feedback.md"
WIKI_INDEX = WIKI / "index.md"
WIKI_LOG = WIKI / "log.md"
STRATEGY_STATE = state_paths.state_file("x_growth_strategy.json", seed_from_legacy=False)
POST_JOB_NAME = os.environ.get("X_POST_CRON_NAME", "X posting via xposting profile")
ENGAGE_JOB_NAME = os.environ.get("X_ENGAGE_CRON_NAME", "X engagement polling via xengaging profile")
URL_RE = re.compile(r"https?://")
HASHTAG_RE = re.compile(r"(^|\s)#\w+")


def load_history() -> list[dict[str, Any]]:
    path = state_paths.POSTS_HISTORY
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(rows, key=lambda r: int(r.get("ts") or 0))


def metric(row: dict[str, Any], key: str) -> int:
    return int((row.get("metrics") or {}).get(key) or 0)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    imps = [metric(r, "impression_count") for r in rows if r.get("metrics")]
    likes = sum(metric(r, "like_count") for r in rows)
    replies = sum(metric(r, "reply_count") for r in rows)
    reposts = sum(metric(r, "retweet_count") for r in rows)
    quotes = sum(metric(r, "quote_count") for r in rows)
    impressions = sum(imps)
    link_posts = sum(1 for r in rows if URL_RE.search(r.get("text", "")))
    hashtag_posts = sum(1 for r in rows if HASHTAG_RE.search(r.get("text", "")))
    return {
        "posts": len(rows),
        "impressions": impressions,
        "median_impressions": statistics.median(imps) if imps else 0,
        "avg_impressions": round(impressions / len(imps), 2) if imps else 0,
        "likes": likes,
        "replies": replies,
        "reposts": reposts,
        "quotes": quotes,
        "engagements": likes + replies + reposts + quotes,
        "engagement_rate_pct": round(((likes + replies + reposts + quotes) / impressions) * 100, 2) if impressions else 0,
        "link_rate_pct": round((link_posts / len(rows)) * 100, 1) if rows else 0,
        "hashtag_rate_pct": round((hashtag_posts / len(rows)) * 100, 1) if rows else 0,
    }


def period_rows(history: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    lo = int(start.timestamp())
    hi = int(end.timestamp())
    return [r for r in history if lo <= int(r.get("ts") or 0) < hi]


def top_rows(rows: list[dict[str, Any]], n: int = 8) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            metric(r, "impression_count"),
            metric(r, "like_count") + metric(r, "reply_count") * 2 + metric(r, "retweet_count") * 3,
        ),
        reverse=True,
    )[:n]


def previous_report_excerpt() -> str:
    if not REPORT_PAGE.exists():
        return ""
    text = REPORT_PAGE.read_text()
    marker = "## Report history"
    if marker not in text:
        return text[-2500:]
    return text.split(marker, 1)[1][-3500:]


def ask_grok(summary: dict[str, Any], recent_posts: list[dict[str, Any]], prior_excerpt: str) -> str:
    post_lines = []
    for r in recent_posts:
        metrics = r.get("metrics") or {}
        post_lines.append(
            f"- {datetime.fromtimestamp(int(r.get('ts') or 0)).date()} "
            f"imps={metrics.get('impression_count', 0)} likes={metrics.get('like_count', 0)} "
            f"replies={metrics.get('reply_count', 0)} strategy={r.get('strategy') or 'legacy'}: "
            f"{r.get('text', '')[:260]}"
        )
    prompt = (
        "You are Grok reviewing @anitdotguru's X growth experiment. Give blunt, practical feedback. "
        "Do not add a persona name, greeting, signature, or roleplay label.\n"
        "Account positioning: pragmatic AI-builder / homelab / self-hosting / agent-ops realism.\n"
        "Goals: grow followers by increasing useful replies, saves/reposts, and profile curiosity; avoid engagement bait.\n\n"
        "Compare the latest week to the previous week and the first-round baseline. Look for deltas.\n"
        "Then propose concrete changes to post formats, reply behavior, topics, and cadence.\n"
        "Be concise but specific. Include a section named `Cron guidance` with one of: reduce, hold, increase.\n\n"
        f"Metrics JSON:\n{json.dumps(summary, indent=2, sort_keys=True)}\n\n"
        f"Top/recent posts:\n" + "\n".join(post_lines) + "\n\n"
        f"Prior report excerpts, if any:\n{prior_excerpt[-2500:]}\n"
    )
    try:
        feedback = run_hermes_prompt(
            prompt,
            profile=os.getenv("HERMES_AUDIT_PROFILE", "xposting"),
            provider=os.getenv("GROK_AUDIT_PROVIDER", "xai-oauth"),
            model=os.getenv("GROK_AUDIT_MODEL", "grok-4.3"),
            toolsets=os.getenv("HERMES_AUTOMATION_TOOLSETS", "terminal"),
            timeout=360,
            source="x-growth-audit",
        ).strip()
        return re.sub(r"^(Kryten|Grok|Hermes):\s*", "", feedback, flags=re.I)
    except Exception as exc:
        return (
            f"Grok audit failed: {exc}\n\n"
            "Fallback: keep reducing link-first posts, keep hashtags rare, and use more first-person operator notes until median impressions and replies improve."
        )


def decide_schedules(latest: dict[str, Any]) -> dict[str, str]:
    posts = latest["posts"]
    median_imps = float(latest["median_impressions"] or 0)
    active_engagement = int(latest["replies"] + latest["reposts"] + latest["quotes"])
    engagement_rate = float(latest["engagement_rate_pct"] or 0)

    # Conservative default after the first audit: fewer, better posts.
    post_schedule = "0 10,18 * * *"
    if posts >= 3 and median_imps < 10 and active_engagement == 0:
        post_schedule = "0 10 * * *"
    elif posts >= 5 and median_imps >= 50 and active_engagement >= 2 and engagement_rate >= 4:
        post_schedule = "0 9,15,21 * * *"

    # Mentions are currently sparse; poll less often unless conversation starts showing up.
    engage_schedule = "20 */2 * * *"
    if active_engagement >= 3:
        engage_schedule = "20 * * * *"

    return {"post_schedule": post_schedule, "engage_schedule": engage_schedule}


def find_cron_job_id(name: str) -> str | None:
    try:
        out = subprocess.check_output(["hermes", "cron", "list", "--all"], text=True, timeout=60)
    except Exception as exc:
        print(f"cron list failed: {exc}", file=sys.stderr)
        return None
    current_id = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped and " [" in stripped:
            current_id = stripped.split()[0]
        if stripped == f"Name:      {name}" and current_id:
            return current_id
    return None


def current_cron_schedule(name: str) -> str | None:
    try:
        out = subprocess.check_output(["hermes", "cron", "list", "--all"], text=True, timeout=60)
    except Exception:
        return None
    current_name = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            current_name = stripped.split("Name:", 1)[1].strip()
        elif current_name == name and stripped.startswith("Schedule:"):
            return stripped.split("Schedule:", 1)[1].strip()
    return None


def apply_schedule(name: str, desired: str) -> str:
    current = current_cron_schedule(name)
    if current == desired:
        return f"{name}: already {desired}"
    job_id = find_cron_job_id(name)
    if not job_id:
        return f"{name}: job not found; wanted {desired}"
    try:
        subprocess.check_call(["hermes", "cron", "edit", job_id, "--schedule", desired], timeout=60)
        return f"{name}: {current or 'unknown'} -> {desired}"
    except Exception as exc:
        return f"{name}: failed to set {desired}: {exc}"


def update_obsidian_report(date_s: str, summary: dict[str, Any], grok_feedback: str, schedules: dict[str, str], apply_results: list[str]) -> None:
    REPORT_PAGE.parent.mkdir(parents=True, exist_ok=True)
    if REPORT_PAGE.exists():
        text = REPORT_PAGE.read_text()
        text = re.sub(r"updated: \d{4}-\d{2}-\d{2}", f"updated: {date_s}", text, count=1)
    else:
        text = f"""---
title: X Growth Feedback
created: {date_s}
updated: {date_s}
type: query
tags: [project, ai, personal]
sources:
  - /Users/sva/.local/state/home-ops/x-social/posts.jsonl
confidence: medium
contested: false
---

# X Growth Feedback

Purpose: track @anitdotguru X follower-growth experiments so future Hermes/Grok wake-ups can compare deltas instead of starting cold.

## First-round baseline — 2026-05-21

Initial local audit of recent posting history found 48 posts from Apr 21 → May 9 with 720 total impressions, 38 likes, 2 replies, 0 reposts, and 0 quotes. Every post included a link, and 32/48 used hashtags, mostly `#agentdev` / `#selfhosted`. The feed read too much like automated article commentary.

Initial strategy changes:

- Make fewer external-link-first posts.
- Prefer first-person `I built / I broke / I learned` operator lessons.
- Use fewer hashtags.
- Build a repeatable agent-infra realism lane: evals, logs, retries, auth, queues, state, rollback, cost ceilings, and data portability.
- Reply more to relevant builders, but keep replies specific and useful.
- Keep the self-hosted / anti-lock-in angle, but vary examples so the feed does not sound repetitive.

## Report history
"""
    entry = f"""

### {date_s} weekly Grok audit

#### Metrics snapshot

```json
{json.dumps(summary, indent=2, sort_keys=True)}
```

#### Grok feedback

{grok_feedback}

#### Cron tuning

- Desired posting schedule: `{schedules['post_schedule']}`
- Desired engagement polling schedule: `{schedules['engage_schedule']}`
- Apply results:
"""
    for result in apply_results:
        entry += f"  - {result}\n"
    REPORT_PAGE.write_text(text.rstrip() + entry)

    if WIKI_INDEX.exists():
        idx = WIKI_INDEX.read_text()
        line = "- [[x-growth-feedback]] — Weekly @anitdotguru X growth audits, strategy deltas, and cron-cadence tuning."
        if line not in idx:
            idx = idx.replace("## Queries\n", f"## Queries\n\n{line}\n")
            idx = re.sub(r"Last updated: \d{4}-\d{2}-\d{2}", f"Last updated: {date_s}", idx, count=1)
            WIKI_INDEX.write_text(idx)

    log_line = f"- {date_s}: Appended weekly @anitdotguru X growth audit to `queries/x-growth-feedback.md`.\n"
    WIKI_LOG.parent.mkdir(parents=True, exist_ok=True)
    with WIKI_LOG.open("a") as f:
        f.write(log_line)


def concise_recall(summary: dict[str, Any], grok_feedback: str, apply_results: list[str]) -> str:
    """Return a Telegram-friendly TL;DR for no-agent cron stdout delivery."""
    latest = summary.get("latest_7d") or {}
    previous = summary.get("previous_7d") or {}
    grok_ok = not grok_feedback.lower().startswith("grok audit failed:")

    def pct_change(current: Any, prior: Any) -> str:
        try:
            current_f = float(current or 0)
            prior_f = float(prior or 0)
        except (TypeError, ValueError):
            return "n/a"
        if prior_f == 0:
            return "n/a"
        return f"{((current_f - prior_f) / prior_f) * 100:+.0f}%"

    feedback_lines = [ln.strip("- ").strip() for ln in grok_feedback.splitlines() if ln.strip()]
    bullets: list[str] = []
    for line in feedback_lines:
        if line.lower().startswith(("latest week", "post formats:", "reply behavior:", "topics:", "cadence:")):
            bullets.append(line)
        if len(bullets) >= 3:
            break
    if not bullets and feedback_lines:
        bullets = feedback_lines[:3]

    lines = [
        "Weekly Grok X growth audit complete",
        f"Obsidian report: {REPORT_PAGE}",
        "",
        "TL;DR:",
        f"- Grok LLM used: {'yes' if grok_ok else 'no/fallback'} ({os.getenv('GROK_AUDIT_PROVIDER', 'xai-oauth')} / {os.getenv('GROK_AUDIT_MODEL', 'grok-4.3')})",
        "- Vault MCP used: yes (social/X + Postgres secrets loaded via vault_mcp_social_env.py)",
        "- X metrics source: Tweepy/X API credentials from Vault MCP, not the xurl CLI",
        f"- Metrics refresh log: {os.getenv('X_GROWTH_FETCH_METRICS_LOG', '(not set)')}",
        f"- Latest 7d: {latest.get('posts', 0)} posts, {latest.get('impressions', 0)} impressions ({pct_change(latest.get('impressions'), previous.get('impressions'))}), {latest.get('engagements', 0)} engagements ({pct_change(latest.get('engagements'), previous.get('engagements'))}), engagement rate {latest.get('engagement_rate_pct', 0)}%",
        "- Cron tuning: " + "; ".join(apply_results),
    ]
    if bullets:
        lines.append("")
        lines.append("Recall:")
        lines.extend(f"- {bullet}" for bullet in bullets)
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(timezone.utc)
    date_s = now.astimezone().date().isoformat()
    history = load_history()
    latest_rows = period_rows(history, now - timedelta(days=7), now)
    previous_rows = period_rows(history, now - timedelta(days=14), now - timedelta(days=7))
    all_summary = summarize(history)
    latest = summarize(latest_rows)
    previous = summarize(previous_rows)
    summary = {
        "generated_at": now.isoformat(),
        "all_time": all_summary,
        "latest_7d": latest,
        "previous_7d": previous,
        "delta_latest_vs_previous": {
            key: latest.get(key, 0) - previous.get(key, 0)
            for key in ("posts", "impressions", "likes", "replies", "reposts", "quotes", "engagements")
        },
    }
    schedules = decide_schedules(latest)
    prior_excerpt = previous_report_excerpt()
    grok_feedback = ask_grok(summary, top_rows(latest_rows or history), prior_excerpt)

    apply_results = []
    if os.getenv("X_GROWTH_AUTOTUNE_CRONS", "1").lower() not in {"0", "false", "no"}:
        apply_results.append(apply_schedule(POST_JOB_NAME, schedules["post_schedule"]))
        apply_results.append(apply_schedule(ENGAGE_JOB_NAME, schedules["engage_schedule"]))
    else:
        apply_results.append("autotune disabled by X_GROWTH_AUTOTUNE_CRONS")

    STRATEGY_STATE.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_STATE.write_text(json.dumps({"summary": summary, "schedules": schedules, "apply_results": apply_results}, indent=2, sort_keys=True))
    update_obsidian_report(date_s, summary, grok_feedback, schedules, apply_results)
    print(concise_recall(summary, grok_feedback, apply_results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
