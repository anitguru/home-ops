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

# AI-related keywords to match in email subjects/senders
AI_KEYWORDS = [
    "claude", "anthropic", "openai", "gpt", "chatgpt", "ollama", "hermes",
    "hermes-agent", "pi-agent", "moonshot", "kimi", "mistral", "llama",
    "gemini", "deepmind", "hugging face", "huggingface", "open model",
    "open-weight", "open source model", "diffusion", "midjourney",
    "stability", "stablediffusion", "perplexity", "grok", "xai",
    "cohere", "ai21", "fal", "replicate", "modal", "together ai",
    "runpod", "vast.ai", "cursor", "windsurf", "zed", "continue",
    "mcp", "model context protocol", "agent", "agentic", "rag",
    "fine-tune", "fine-tuning", "fine tune", "fine tuning", "quantization",
    "gguf", "ggml", "lora", "qlora", "vllm", "sglang", "tgi",
    "text-to-speech", "tts", "whisper", "embedding", "reranker",
    "vector db", "vector database", "pinecone", "qdrant", "weaviate",
    "milvus", "chroma", "langchain", "llamaindex", "crewai", "autogen",
    "n8n", "windmill", "dify", "flowise", "fastgpt",
]

# Senders/domains that are always interesting (allowlist)
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

def is_ai_related(subject: str, sender: str) -> bool:
    """Check if email is AI-related based on subject/sender.

    Uses stricter matching: sender domain allowlist is always trusted,
    but keyword matches require the keyword to be a word boundary match
    (not a substring of a larger word) to avoid false positives like
    'agent' in 'insurance agent' or 'rag' in 'fragrant'.
    """
    text = (subject + " " + sender).lower()
    # Check sender domain allowlist (trusted senders)
    for domain in AI_SENDER_DOMAINS:
        if domain in sender.lower():
            return True
    # Check keywords with word-boundary matching for short/common terms
    SHORT_KEYWORDS = {"agent", "rag", "mcp", "tts", "tgi", "zed", "fal", "n8n", "dify"}
    for kw in AI_KEYWORDS:
        if kw in SHORT_KEYWORDS:
            # Use word boundary for short/common terms
            if re.search(r'\b' + re.escape(kw) + r'\b', text):
                return True
        else:
            if kw in text:
                return True
    return False


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
            lines = block.split("\r\n")
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
            # Only match on subject + sender (NOT content) to avoid false positives
            if msg.get("subject") and is_ai_related(msg.get("subject", ""), msg.get("sender", "")):
                msg["source"] = "apple_mail"
                emails.append(msg)

        print(f"Apple Mail: found {len(emails)} AI-related emails")
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
            if msg.get("subject") and is_ai_related(msg.get("subject", ""), msg.get("sender", "")):
                msg["source"] = "proton"
                emails.append(msg)

        print(f"Proton: found {len(emails)} AI-related emails")
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
# Tweet drafting
# ---------------------------------------------------------------------------

POST_TEMPLATE = """You are @anitdotguru — a pragmatic technical operator who builds with AI agents, homelabs, and self-hosted tools. Conversational, never corporate. You share what you learned the hard way.

Growth feedback to apply:
- Be specific and opinionated, not generic.
- No emojis spam (one max if very fitting).
- Max one contextual hashtag. No generic #AI/#tech.
- No "the future of", "game changer", "worth watching".
- Include the key fact (model name, what changed) in the first line.

Template guardrails:
- First line: the news headline (model name + what happened).
- Second section: 1-2 sentences of context (what it is, why it matters to builders).
- Third section: a practical command or action link if present in the email.
- End with one contextual hashtag max.

Source email:
Subject: {subject}
From: {sender}
Body snippet: {body}

Write one X post under 270 chars. After the post body, on a new line write `HASHTAGS:` with zero or one contextual tag."""


def craft_tweet(email_msg: dict, history: list[dict] | None = None) -> str | None:
    """Draft a tweet from the email content using Hermes one-shot LLM."""
    if os.getenv("RADAR_USE_LLM", "1").lower() in {"0", "false", "no"}:
        return craft_tweet_fallback(email_msg)

    prompt = POST_TEMPLATE.format(
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
        return craft_tweet_fallback(email_msg)

    hashtag_suffix = ""
    if "\nHASHTAGS:" in raw:
        body_part, tag_part = raw.rsplit("\nHASHTAGS:", 1)
        tags = [t for t in tag_part.strip().split() if t.startswith("#")]
        # Filter generic tags
        generic = {"#ai", "#tech", "#technology", "#startup", "#startups"}
        tags = [t for t in tags if t.lower() not in generic]
        if tags:
            hashtag_suffix = " " + tags[0]
        raw = body_part

    body = raw.strip().strip('"').strip("'")
    body_budget = MAX_LEN - len(hashtag_suffix)
    if len(body) > body_budget:
        body = textwrap.shorten(body, width=body_budget, placeholder="…")

    return f"{body}{hashtag_suffix}"


def craft_tweet_fallback(email_msg: dict) -> str:
    """Deterministic fallback if LLM is unavailable."""
    subject = email_msg.get("subject", "").strip().rstrip(".")
    body = textwrap.shorten(subject, width=MAX_LEN - 10, placeholder="…")
    return body


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_to_x(text: str) -> tuple[str, str]:
    """Post to X via tweepy. Returns (tweet_url, tweet_id)."""
    client = tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    resp = client.create_tweet(text=text)
    tid = resp.data["id"]
    return f"https://x.com/anitdotguru/status/{tid}", tid


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
    print(f"\nTotal AI-related emails found: {len(all_emails)}")

    if not all_emails:
        print("No AI-related emails found — nothing to post")
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
    print(f"After dedup: {len(new_emails)} new emails to post")

    if not new_emails:
        print("All emails already posted — skipping")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 0

    # Limit to 1 post per run to avoid spam
    email_msg = new_emails[0]
    subject = email_msg.get("subject", "").strip()
    subj_hash = content_hash(subject)
    print(f"\nSelected: {subject}")
    print(f"  From: {email_msg.get('sender', '')}")
    print(f"  Source: {email_msg.get('source', '')}")

    # Draft tweet
    text = craft_tweet(email_msg, history)
    if not text:
        print("Failed to draft tweet — skipping")
        state["last_run"] = dt.datetime.now(dt.UTC).isoformat()
        save_state(state)
        if db:
            db.close()
        return 1

    method = "llm" if os.getenv("RADAR_USE_LLM", "1").lower() not in {"0", "false", "no"} else "fallback"
    print(f"\nDrafted [{method}] ({len(text)} chars): {text}")

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
        tweet_url, tweet_id = post_to_x(text)
        print(f"Posted: {tweet_url}")
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
        "text": text,
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

    print(f"\nRadar complete. Posted 1 of {len(new_emails)} new AI emails.")
    return 0


if __name__ == "__main__":
    sys.exit(main())