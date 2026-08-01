#!/usr/bin/env python3
"""
AI News Radar — scans Apple Mail + Proton Bridge for AI-related email updates,
deduplicates against the Postgres posts table, drafts and posts to X via
tweepy, and logs the result back to Postgres + state JSONL.

Runs as a no-agent Hermes cron. Uses a Hermes one-shot LLM call to draft the
tweet with template guardrails.

State file: ~/.local/state/home-ops/x-social/radar_cursor.json
    { "last_apple_mail_date": "...", "last_proton_uid": N, "posted_subjects": [...] }

Dedup strategy:
  1. Content hash of subject line checked against posts.content_hash
  2. Source URL (if extractable) checked against posts.source_url
  3. Subject similarity: exact subject match in posted_subjects state list

Quiet hours: 23:00–08:00 ET (like engage_actions_cron.sh)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
import tweepy

try:
    from scripts import social_db, state_paths
except Exception:  # pragma: no cover
    import social_db
    import state_paths

HOME_OPS_HERMES_SCRIPTS = Path(os.environ.get(
    "HOME_OPS_HERMES_SCRIPTS",
    "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
))
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))
from hermes_llm import run_hermes_prompt

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLATFORM = "x"
PERSONA = "anitdotguru"
MAX_LEN = 280
URL_COST = 24

STATE_DIR = Path(os.environ.get(
    "X_SOCIAL_STATE_DIR",
    os.path.expanduser("~/.local/state/home-ops/x-social"),
))
STATE_FILE = STATE_DIR / "radar_cursor.json"
HISTORY = state_paths.POSTS_HISTORY

# High-signal topics. Generic words such as "AI", "agent", "RAG", and vendor
# names alone are intentionally insufficient. A message must also describe a
# concrete release, availability change, policy event, outage, or similarly
# material development.
HIGH_SIGNAL_TOPICS = [
    # Models / model labs / open weights
    "model weights", "open weights", "open-weight", "open weight", "checkpoint",
    "foundation model", "language model", "multimodal model", "reasoning model",
    "mixture of experts", "moe model", "parameter model", "model release",
    "claude", "anthropic", "openai", "gpt-", "chatgpt", "gemini", "deepmind",
    "grok", "xai", "kimi", "moonshot", "mistral", "llama", "qwen", "deepseek",
    "phi-", "command r", "cohere", "ai21", "nous research", "nousresearch",
    # Harnesses / runtimes / inference and local model distribution
    "agent harness", "coding harness", "coding agent", "agent runtime",
    "agent framework", "tool-use", "tool use", "model context protocol", "mcp server",
    "hermes agent", "hermes-agent", "openclaw", "pi-agent", "claude code", "codex cli",
    "ollama", "ollama cloud", "hugging face", "huggingface", "vllm", "sglang",
    "gguf", "quantization", "inference engine", "model serving", "local model",
]

RELEASE_EVENTS = [
    "released", "releases", "launches", "launched", "launching", "unveils",
    "unveiled", "introducing", "announcing", "now available", "available now",
    "available on", "ships today", "weights available", "open-sourced", "open sourced",
    "lands on", "rolls out", "rolling out", "is here", "general availability",
]

CAPACITY_EVENTS = [
    "capacity", "demand exceeds", "demand outstrips", "not accepting", "waitlist",
    "sold out", "paused signups", "pauses signups", "quota", "rate limit",
    "overloaded", "service unavailable", "availability limited",
]

MAJOR_EVENTS = [
    "blocked by", "government blocked", "banned", "ban on", "export control",
    "sanctioned", "prohibited", "restriction", "shut down", "shuts down",
    "security breach", "data breach", "major outage", "acquired", "acquisition",
    "merger", "cease and desist", "injunction", "antitrust", "investigation",
]

PROMOTIONAL_TERMS = [
    "webinar", "register now", "save your seat", "book a demo", "request a demo",
    "limited time", "special offer", "sale", "discount", "coupon", "sponsored",
    "partner offer", "case study", "customer story", "whitepaper", "ebook",
    "weekly digest", "monthly roundup", "top stories", "newsletter edition",
    "last chance", "don't miss", "do not miss", "free trial", "upgrade today",
]

# First-party/credible sender domains. These add confidence but never qualify an
# email without a high-signal topic and concrete news event.
AI_SENDER_DOMAINS = [
    "ollama.com", "anthropic.com", "openai.com", "xai.com",
    "mistral.ai", "huggingface.co", "stability.ai", "cohere.com",
    "perplexity.ai", "together.ai", "modal.com", "replicate.com",
    "huggingface.com", "moonshot.ai", "ai21.com", "fal.ai",
    "nousresearch.com", "deepmind.google", "googleblog.com",
    "github.com",  # release notifications
]

# Proton Bridge SSH host
PROTON_SSH_HOST = os.environ.get("PROTON_SSH_HOST", "proton")
PROTON_ACCOUNT = "anitguru@proton.me"
PROTON_BRIDGE_PW = "/etc/proton-bridge/bridge.pw"

# Apple Mail osascript path
APPLE_MAIL_SCRIPT = """
tell application "Mail"
  set results to ""
  set allMailboxes to every mailbox of account 1
  repeat with mb in allMailboxes
    try
      set theMessages to every message of mb whose date received is greater than (current date) - (1 * days)
      repeat with msg in theMessages
        set msgSubject to subject of msg
        set msgSender to sender of msg
        set msgDate to date received of msg
        set msgContent to content of msg
        set results to results & "###MSG###" & return
        set results to results & "Subject: " & msgSubject & return
        set results to results & "From: " & msgSender & return
        set results to results & "Date: " & msgDate & return
        set results to results & "Content: " & msgContent & return
      end repeat
    end try
  end repeat
  return results
end tell
"""

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"posted_hashes": [], "last_run": None}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"posted_hashes": [], "last_run": None}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Keep posted_hashes bounded to last 500 entries
    if len(state.get("posted_hashes", [])) > 500:
        state["posted_hashes"] = state["posted_hashes"][-500:]
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# Email scanning
# ---------------------------------------------------------------------------

def radar_signal(subject: str, sender: str, body: str = "") -> tuple[bool, int, str]:
    """Return strict deterministic news-candidate status, score, and rationale.

    Sender reputation helps rank a candidate but never qualifies it by itself.
    The email must contain a high-signal topic *and* a concrete event. Generic
    AI marketing, webinars, roundups, case studies, and company newsletters fail
    closed unless they also contain an unmistakably major event.
    """
    subject_l = subject.lower().strip()
    sender_l = sender.lower()
    body_l = body.lower()[:5000]
    full_text = f"{subject_l}\n{body_l}"

    topic_hits = [term for term in HIGH_SIGNAL_TOPICS if term in full_text]
    subject_topics = [term for term in HIGH_SIGNAL_TOPICS if term in subject_l]
    release_hits = [term for term in RELEASE_EVENTS if term in full_text]
    capacity_hits = [term for term in CAPACITY_EVENTS if term in full_text]
    major_hits = [term for term in MAJOR_EVENTS if term in full_text]
    event_hits = release_hits + capacity_hits + major_hits
    subject_events = [term for term in RELEASE_EVENTS + CAPACITY_EVENTS + MAJOR_EVENTS if term in subject_l]
    promo_hits = [term for term in PROMOTIONAL_TERMS if term in subject_l]
    trusted = any(domain in sender_l for domain in AI_SENDER_DOMAINS)

    if not topic_hits or not event_hits:
        missing = "topic" if not topic_hits else "concrete event"
        return False, 0, f"missing high-signal {missing}"

    score = 0
    score += 3 if subject_topics else 1
    score += 3 if subject_events else 1
    score += 4 if major_hits else 0
    score += 3 if capacity_hits else 0
    score += 1 if trusted else 0
    score -= 5 if promo_hits else 0

    # Release announcements need the topic or event in the subject. Major policy,
    # capacity, security, and availability events may qualify from a terse subject
    # when the body supplies the model/harness context.
    subject_grounded = bool(subject_topics or subject_events)
    accepted = score >= 5 and (subject_grounded or bool(major_hits or capacity_hits))
    reason = (
        f"topics={topic_hits[:3]}; events={event_hits[:3]}; "
        f"trusted={trusted}; promo={promo_hits[:2]}; score={score}"
    )
    return accepted, score, reason


def is_ai_related(subject: str, sender: str, body: str = "") -> bool:
    """Compatibility wrapper for the strict radar candidate gate."""
    return radar_signal(subject, sender, body)[0]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def scan_apple_mail() -> list[dict[str, str]]:
    """Scan Apple Mail via osascript for AI-related emails from the last 24h."""
    try:
        result = subprocess.run(
            ["osascript", "-e", APPLE_MAIL_SCRIPT],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"Apple Mail osascript failed: {result.stderr[:200]}")
            return []

        raw = result.stdout
        if not raw.strip():
            return []

        emails = []
        for block in raw.split("###MSG###"):
            block = block.strip()
            if not block:
                continue
            msg = {}
            # osascript may emit LF or CRLF depending on the message/source.
            # splitlines() handles both; splitting only on CRLF caused forwarded
            # emails to collapse into one giant subject with blank sender/body.
            lines = block.splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith("Subject: "):
                    msg["subject"] = line[len("Subject: "):]
                elif line.startswith("From: "):
                    msg["sender"] = line[len("From: "):]
                elif line.startswith("Date: "):
                    msg["date"] = line[len("Date: "):]
                elif line.startswith("Content: "):
                    # Content is the rest of the block after "Content: "
                    content_start = block.index("Content: ")
                    msg["content"] = block[content_start + len("Content: "):].strip()
                    break  # Content is the last field, stop parsing lines
            if msg.get("subject") and is_ai_related(
                msg.get("subject", ""), msg.get("sender", ""), msg.get("content", "")
            ):
                accepted, score, reason = radar_signal(
                    msg.get("subject", ""), msg.get("sender", ""), msg.get("content", "")
                )
                msg["radar_score"] = score
                msg["radar_reason"] = reason
                msg["source"] = "apple_mail"
                emails.append(msg)

        print(f"Apple Mail: found {len(emails)} strict news candidates")
        return emails
    except subprocess.TimeoutExpired:
        print("Apple Mail osascript timed out")
        return []
    except Exception as exc:
        print(f"Apple Mail scan error: {exc}")
        return []


def scan_proton() -> list[dict[str, str]]:
    """Scan Proton Bridge via SSH for AI-related recent emails."""
    script = f"""
import email, imaplib, ssl, re
from email.header import decode_header, make_header

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

password = open('{PROTON_BRIDGE_PW}').read().strip()
M = imaplib.IMAP4('127.0.0.1', 1144)
M.starttls(ssl_context=ctx)
M.login('{PROTON_ACCOUNT}', password)

results = []
for folder in ['INBOX']:
    M.select(folder, readonly=True)
    # Search for emails from last 24h
    typ, data = M.uid('search', None, 'SINCE', '24-Jul-2026')
    if typ != 'OK' or not data or not data[0].strip():
        continue
    uids = data[0].split()
    for uid in uids[-30:]:  # last 30 max
        typ, msgdata = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
        if typ != 'OK':
            continue
        raw = b''.join(part[1] for part in msgdata if isinstance(part, tuple))
        msg = email.message_from_bytes(raw)
        subject = str(make_header(decode_header(msg.get('Subject', ''))))
        sender = str(make_header(decode_header(msg.get('From', ''))))
        date = msg.get('Date', '')
        # Fetch body snippet
        typ2, bodydata = M.uid('fetch', uid, '(BODY.PEEK[1])')
        body_snippet = ''
        if typ2 == 'OK':
            for part in bodydata:
                if isinstance(part, tuple):
                    try:
                        body_snippet = part[1].decode('utf-8', errors='replace')[:1500]
                    except:
                        body_snippet = str(part[1][:1500])
        results.append(f"SUBJECT|||{{subject}}\\nSENDER|||{{sender}}\\nDATE|||{{date}}\\nBODY|||{{body_snippet}}\\nUID|||{{uid.decode()}}")

M.logout()
print('\\n---EMAIL---\\n'.join(results) if results else 'NO_RESULTS')
"""
    # Write script to temp, scp to proton, run it
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        tmp = f.name

    try:
        # Dynamic date injection
        today = dt.date.today()
        yesterday = today - dt.timedelta(days=2)
        date_str = yesterday.strftime("%d-%b-%Y")
        script_fixed = script.replace("24-Jul-2026", date_str)
        with open(tmp, "w") as f:
            f.write(script_fixed)

        # scp and run
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        tmp, f"{PROTON_SSH_HOST}:/tmp/radar_scan.py"],
                       timeout=30, check=True)
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             PROTON_SSH_HOST, "python3 /tmp/radar_scan.py"],
            capture_output=True, text=True, timeout=60,
        )
        os.unlink(tmp)

        if result.returncode != 0:
            print(f"Proton SSH failed: {result.stderr[:200]}")
            return []

        raw = result.stdout.strip()
        if not raw or raw == "NO_RESULTS":
            print("Proton: no recent emails")
            return []

        emails = []
        for block in raw.split("\n---EMAIL---\n"):
            block = block.strip()
            if not block:
                continue
            msg = {}
            for line in block.split("\n"):
                if line.startswith("SUBJECT|||"):
                    msg["subject"] = line[len("SUBJECT|||"):]
                elif line.startswith("SENDER|||"):
                    msg["sender"] = line[len("SENDER|||"):]
                elif line.startswith("DATE|||"):
                    msg["date"] = line[len("DATE|||"):]
                elif line.startswith("BODY|||"):
                    msg["content"] = line[len("BODY|||"):]
                elif line.startswith("UID|||"):
                    msg["uid"] = line[len("UID|||"):]
            if msg.get("subject") and is_ai_related(
                msg.get("subject", ""), msg.get("sender", ""), msg.get("content", "")
            ):
                accepted, score, reason = radar_signal(
                    msg.get("subject", ""), msg.get("sender", ""), msg.get("content", "")
                )
                msg["radar_score"] = score
                msg["radar_reason"] = reason
                msg["source"] = "proton"
                emails.append(msg)

        print(f"Proton: found {len(emails)} strict news candidates")
        return emails
    except Exception as exc:
        print(f"Proton scan error: {exc}")
        if os.path.exists(tmp):
            os.unlink(tmp)
        return []


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def is_already_posted(email_msg: dict, state: dict, db_conn) -> bool:
    """Check if this email has already been posted to X."""
    subject = email_msg.get("subject", "").strip()
    subj_hash = content_hash(subject)

    # 1. Check state file
    if subj_hash in state.get("posted_hashes", []):
        return True

    # 2. Check Postgres by content_hash
    if db_conn:
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM posts WHERE platform=%s AND persona=%s AND content_hash=%s LIMIT 1",
                    (PLATFORM, PERSONA, subj_hash),
                )
                if cur.fetchone():
                    return True
        except Exception:
            pass  # DB issues shouldn't block posting

    return False


# ---------------------------------------------------------------------------
# Newsworthiness adjudication and tweet drafting
# ---------------------------------------------------------------------------

NEWSWORTHINESS_TEMPLATE = """You are the strict editor for @anitdotguru's AI news radar.

Decide which email, if any, is genuinely new and important enough to post to X. This is not a general AI newsletter. Be highly selective.

POST only for material developments such as:
- a new model or major model version, especially open weights/checkpoints;
- a meaningful agent harness, coding harness, runtime, inference, or local-model distribution release;
- consequential access/availability/capacity news (for example, a model reaching Ollama Cloud but subscriptions being paused because demand exceeds capacity);
- major government/legal action, blocking, export controls, shutdowns, security incidents, major outages, or acquisitions affecting AI builders.

REJECT:
- advertisements, webinars, demos, discounts, case studies, ebooks, sponsored mail, and sales outreach;
- generic company updates that merely say "AI";
- weekly digests, roundups, opinion pieces, tutorials, and recycled stories;
- minor product features or vague announcements with no concrete new event.

Important: first-party announcements and credible direct email reports are sufficient. Do NOT require Hacker News, Reddit, or mainstream coverage. The goal is to catch important news early, before aggregators cover it.

Return ONLY a JSON array with one object per input item:
{{"id": 0, "score": 0-100, "post": true|false, "event_type": "model|open_weights|harness|availability|policy|security|outage|business|other", "reason": "brief factual reason"}}

Set post=true only at score 80 or above. If none qualify, every item must have post=false.

Candidates:
{candidates}
"""


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from a strict or fenced LLM response."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("no JSON array in triage response")
    parsed = json.loads(cleaned[start:end + 1])
    if not isinstance(parsed, list):
        raise ValueError("triage response was not a list")
    return [item for item in parsed if isinstance(item, dict)]


def rank_newsworthy_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only high-confidence news, ordered by editorial importance.

    The LLM evaluates all candidates in one call. Failure is conservative: only
    deterministic candidates scoring at least 8 survive, so an unavailable LLM
    cannot turn broad keyword matches into posts.
    """
    if not candidates:
        return []

    compact = []
    for idx, item in enumerate(candidates[:20]):
        compact.append({
            "id": idx,
            "subject": item.get("subject", ""),
            "sender": item.get("sender", ""),
            "body": item.get("content", "")[:1200],
            "deterministic_score": item.get("radar_score", 0),
            "deterministic_reason": item.get("radar_reason", ""),
        })

    use_llm = os.getenv("RADAR_TRIAGE_LLM", "1").lower() not in {"0", "false", "no"}
    if use_llm:
        try:
            raw = run_hermes_prompt(
                NEWSWORTHINESS_TEMPLATE.format(candidates=json.dumps(compact, indent=2)),
                provider=os.getenv("RADAR_LLM_PROVIDER") or os.getenv("HERMES_POSTING_PROVIDER"),
                model=os.getenv("RADAR_LLM_MODEL") or os.getenv("HERMES_POSTING_MODEL"),
                toolsets=os.getenv("HERMES_AUTOMATION_TOOLSETS", "terminal"),
                timeout=240,
                source="radar-triage",
            ).strip()
            verdicts = _extract_json_array(raw)
            qualifying = []
            for verdict in verdicts:
                raw_idx = verdict.get("id")
                if raw_idx is None:
                    continue
                try:
                    idx = int(raw_idx)
                    score = int(verdict.get("score", 0))
                except (TypeError, ValueError):
                    continue
                if not (0 <= idx < len(candidates)):
                    continue
                if verdict.get("post") is True and score >= 80:
                    item = dict(candidates[idx])
                    item["news_score"] = score
                    item["news_reason"] = str(verdict.get("reason", ""))
                    item["event_type"] = str(verdict.get("event_type", "other"))
                    qualifying.append(item)
            return sorted(
                qualifying,
                key=lambda item: (item.get("news_score", 0), item.get("radar_score", 0)),
                reverse=True,
            )
        except Exception as exc:
            print(f"Newsworthiness triage failed; using strict deterministic fallback: {exc}")

    fallback = [dict(item) for item in candidates if int(item.get("radar_score", 0)) >= 8]
    for item in fallback:
        item["news_score"] = int(item.get("radar_score", 0)) * 10
        item["news_reason"] = "strict deterministic fallback"
    return sorted(fallback, key=lambda item: item.get("radar_score", 0), reverse=True)

THREAD_TEMPLATE = """You are @anitdotguru — a pragmatic technical operator who builds with AI agents, homelabs, and self-hosted tools. Conversational, never corporate. You share what you learned the hard way.

Your task: write a 3-post X thread from this AI news email. Each post must be under 270 chars.

Rules:
- No emoji spam (one max per post if very fitting).
- No generic hashtags (#AI/#tech banned). One contextual tag max, only on post 1.
- No "the future of", "game changer", "worth watching".
- Be specific and opinionated. Use builder/operator voice.
- Do NOT use thread numbering like "1/", "2/", "3/" — X handles threading visually.

POST 1 — The News:
- First line: the headline (model name + what happened).
- 1-2 sentences of context: what it is, why it matters to builders.
- Include a practical command or action link if present in the email.
- End with one contextual hashtag max.

POST 2 — Top 3 Use Cases:
- Share the top 3 concrete use cases for builders/self-hosters.
- Format as a short list (one line per use case, use "•" bullets).
- Be practical and specific — not vague "automation" or "agents".
- Each use case should be something a builder could actually do this week.

POST 3 — The Question:
- Ask the audience what they're going to do with it.
- Be conversational, not engagement-bait. Ask a genuine builder question.
- End with a question mark.

Separate each post with a line containing only `---POST---`.

Source email:
Subject: {subject}
From: {sender}
Body snippet: {body}

Write the 3 posts now. Remember: `---POST---` between each. No code fences."""


def craft_thread(email_msg: dict, history: list[dict] | None = None) -> list[str] | None:
    """Draft a 3-post X thread from the email content using Hermes one-shot LLM.

    Returns a list of 3 strings (one per tweet), or None on failure.
    Falls back to a single-post format if LLM is unavailable.
    """
    if os.getenv("RADAR_USE_LLM", "1").lower() in {"0", "false", "no"}:
        return [craft_tweet_fallback(email_msg)]

    prompt = THREAD_TEMPLATE.format(
        subject=email_msg.get("subject", ""),
        sender=email_msg.get("sender", ""),
        body=email_msg.get("content", "")[:700],
    )

    try:
        raw = run_hermes_prompt(
            prompt,
            provider=os.getenv("RADAR_LLM_PROVIDER") or os.getenv("HERMES_POSTING_PROVIDER"),
            model=os.getenv("RADAR_LLM_MODEL") or os.getenv("HERMES_POSTING_MODEL"),
            toolsets=os.getenv("HERMES_AUTOMATION_TOOLSETS", "terminal"),
            timeout=240,
            source="radar-draft",
        ).strip()
    except Exception as exc:
        print(f"Hermes draft failed: {exc}")
        return [craft_tweet_fallback(email_msg)]

    # Parse the ---POST--- delimited sections
    parts = [p.strip().strip('"').strip("'") for p in raw.split("---POST---")]
    parts = [p for p in parts if p.strip()]

    if len(parts) < 2:
        # LLM didn't produce a thread — treat as single post
        print("LLM produced single post instead of thread — using as-is")
        return [parts[0] if parts else craft_tweet_fallback(email_msg)]

    # Enforce 270 char limit per post
    cleaned = []
    for i, post in enumerate(parts[:3]):  # max 3 posts
        budget = MAX_LEN - 10  # leave room for hashtag suffix if needed
        if len(post) > budget:
            post = textwrap.shorten(post, width=budget, placeholder="…")
        cleaned.append(post)

    # Pad to 3 posts if LLM returned only 2
    while len(cleaned) < 3:
        cleaned.append("What are you building with this? Reply below 👇")

    return cleaned


def craft_tweet_fallback(email_msg: dict) -> str:
    """Deterministic fallback if LLM is unavailable."""
    subject = email_msg.get("subject", "").strip().rstrip(".")
    body = textwrap.shorten(subject, width=MAX_LEN - 10, placeholder="…")
    return body


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_to_x(posts: list[str]) -> tuple[str, str]:
    """Post to X via tweepy. Supports single posts and threads.

    For threads (list with >1 item), each reply is chained via in_reply_to_tweet_id.
    Returns (root_tweet_url, root_tweet_id).
    """
    client = tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )

    # Post the root tweet
    resp = client.create_tweet(text=posts[0])
    root_id = resp.data["id"]
    root_url = f"https://x.com/anitdotguru/status/{root_id}"

    # Post thread replies
    prev_id = root_id
    for i, post_text in enumerate(posts[1:], 1):
        try:
            resp = client.create_tweet(
                text=post_text,
                in_reply_to_tweet_id=prev_id,
            )
            prev_id = resp.data["id"]
            print(f"  Thread post {i+1}: https://x.com/anitdotguru/status/{prev_id}")
        except Exception as exc:
            print(f"  Thread post {i+1} failed: {exc}")
            break

    return root_url, root_id


def append_history(entry: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def is_quiet_hours() -> bool:
    hour_et = dt.datetime.now(dt.UTC).astimezone(
        dt.timezone(dt.timedelta(hours=-5))
    ).hour
    if hour_et >= 23 or hour_et < 8:
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Quiet hours check
    if is_quiet_hours() and os.getenv("RADAR_FORCE", "") != "1":
        print("Quiet hours — skipping radar run")
        return 0

    state = load_state()
    db = social_db.connect()
    if db:
        social_db.ensure_schema(db)

    # Scan both mailboxes
    print("=== Scanning Apple Mail ===")
    apple_emails = scan_apple_mail()
    print("=== Scanning Proton Bridge ===")
    proton_emails = scan_proton()

    all_emails = apple_emails + proton_emails
    print(f"\nTotal strict news candidates found: {len(all_emails)}")

    if not all_emails:
        print("No high-signal AI news candidates found — nothing to post")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 0

    # Load history for context
    history = []
    if HISTORY.exists():
        history = [json.loads(line) for line in HISTORY.read_text().splitlines() if line.strip()]
    if db:
        db_history = social_db.load_post_history(db)
        seen_ids = {h.get("tweet_id") for h in history if h.get("tweet_id")}
        history.extend([h for h in db_history if h.get("tweet_id") not in seen_ids])

    # Filter out already-posted
    new_emails = [e for e in all_emails if not is_already_posted(e, state, db)]
    print(f"After dedup: {len(new_emails)} unseen candidates")

    if not new_emails:
        print("All emails already posted — skipping")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 0

    # Strict editorial ranking. This intentionally does not require Hacker News
    # or other aggregator coverage; credible first-party breaking news qualifies.
    newsworthy = rank_newsworthy_candidates(new_emails)
    print(f"After newsworthiness triage: {len(newsworthy)} post-worthy candidates")
    if not newsworthy:
        print("No candidate met the strict 80/100 editorial threshold — nothing to post")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 0

    # Limit to 1 post per run to avoid spam. Ranking selects the most important,
    # rather than whichever mailbox happened to be scanned first.
    email_msg = newsworthy[0]
    subject = email_msg.get("subject", "").strip()
    subj_hash = content_hash(subject)
    print(f"\nSelected: {subject}")
    print(f"  From: {email_msg.get('sender', '')}")
    print(f"  Source: {email_msg.get('source', '')}")
    print(f"  News score: {email_msg.get('news_score', '')}")
    print(f"  Why: {email_msg.get('news_reason', '')}")

    # Draft thread
    posts = craft_thread(email_msg, history)
    if not posts:
        print("Failed to draft thread — skipping")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 1

    method = "llm" if os.getenv("RADAR_USE_LLM", "1").lower() not in {"0", "false", "no"} else "fallback"
    print(f"\nDrafted [{method}] {len(posts)}-post thread:")
    for i, p in enumerate(posts):
        print(f"  Post {i+1} ({len(p)} chars): {p[:100]}...")

    # Dry run check
    if os.getenv("RADAR_DRY_RUN", "") == "1":
        print("DRY RUN — not posting to X")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        state.setdefault("posted_hashes", []).append(subj_hash)
        save_state(state)
        if db:
            db.close()
        return 0

    # Post to X
    try:
        tweet_url, tweet_id = post_to_x(posts)
        print(f"Posted thread root: {tweet_url}")
    except Exception as exc:
        print(f"X post failed: {exc}")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 1

    # Log to history + DB
    entry = {
        "ts": int(time.time()),
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "source_url": email_msg.get("url", ""),
        "source_title": subject,
        "text": posts[0],  # root post text
        "thread_text": posts,  # full thread
        "method": method,
        "strategy": "email_radar",
        "source_type": email_msg.get("source", ""),
        "includes_source_url_in_post": False,
    }
    append_history(entry)
    if db:
        social_db.upsert_post(db, entry)
        db.close()

    # Update state
    state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
    state.setdefault("posted_hashes", []).append(subj_hash)
    save_state(state)

    print(f"\nRadar complete. Posted the top-ranked item from {len(newsworthy)} qualifying stories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())