#!/usr/bin/env python3
"""Google Recorder call.docx -> structured sva-s1 meeting note.

Runtime is owned by default-profile Hermes cron via home-ops repo wrappers.
Generative structuring is delegated to a subscription-backed Hermes one-shot
profile (default: callnotes) through hermes/scripts/hermes_llm.py, not direct
provider SDKs or CLIs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import requests
from docx import Document

HOME_OPS_HERMES_SCRIPTS = Path(
    os.environ.get(
        "HOME_OPS_HERMES_SCRIPTS",
        "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
    )
)
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))
from hermes_llm import hermes_available, run_hermes_prompt  # noqa: E402

REMOTE = os.environ.get("CALLNOTES_RCLONE_REMOTE", "svagml-remote-gdrive")
VAULT = os.environ.get("CALLNOTES_OBSIDIAN_VAULT", "work")  # sva-s1
VAULT_LABEL = os.environ.get("CALLNOTES_OBSIDIAN_LABEL", "sva-s1")
OBSIDIAN_MCP = os.environ.get("CALLNOTES_OBSIDIAN_MCP_URL", "https://obsidian-mcp.transformers.lan/mcp")
OUTPUT_FOLDER = os.environ.get("CALLNOTES_OUTPUT_FOLDER", "01_Interactions")
TODAY = date.today().isoformat()

# Always present in every note.
FIXED_PARTICIPANTS = ["[[Steve VanAllen]]"]

# Short name -> full Obsidian link (preserved from old automation).
NAME_ALIASES = {
    "[[Steve]]": "[[Steve VanAllen]]",
    "[[steve]]": "[[Steve VanAllen]]",
    "[[Steve vanallen]]": "[[Steve VanAllen]]",
    "[[steve vanallen]]": "[[Steve VanAllen]]",
}

STRUCTURE_PROMPT = """You are converting a Google Recorder transcript into a SentinelOne sales meeting note.
Output ONLY the raw markdown — no commentary, no code fences.

Follow this EXACT format (Mortenson style):

---
date: {date}
agent_readable: true
type: meeting_notes
account: ""
vendor: "[[SentinelOne]]"
product: "[[AI SIEM]]"
opportunity_id: "PLACEHOLDER"
acv: "PLACEHOLDER"
participants:
  - "[[PARTICIPANT_NAME]]"
tags:
  - meeting_notes
---
## 🦴 Big Goal
**One sentence:** The core problem or goal driving this meeting.

## 🎯 Command of the Message

| **Before Scenario (The Pain)** | **After Scenario (Positive Outcomes)** |
| :--- | :--- |
| Pain point 1 | Positive outcome 1 |
| Pain point 2 | Positive outcome 2 |

| **Required Capabilities & Metrics** | **S1 Differentiators & Proof Points** |
| :--- | :--- |
| Capability need 1 | S1 answer 1 |
| Capability need 2 | S1 answer 2 |

## 🏃 Action (To-Do)
- [ ] Action item — Owner

Rules:
- account: always leave as empty string ""
- participants: extract all names mentioned and wrap each in [[...]]. Resolve short first names to full names where known: "Steve" → [[Steve VanAllen]]. Always deduplicate.
- tags: extract 2-4 relevant lowercase tags from content
- opportunity_id and acv: always "PLACEHOLDER" unless explicitly stated in transcript
- product: always exactly [[AI SIEM]]
- vendor: always exactly [[SentinelOne]]
- Command of the Message tables: if this is a test/short transcript with no real content, put "N/A — test message" in each cell
- Big Goal: if test transcript, write "N/A — test message"
- Action items: if none found, write "- [ ] Follow up — Owner TBD"
- Omit ## 🛠️ The Tech section unless the transcript contains substantial technical discussion

Transcript:
{transcript}"""


class CallnotesError(RuntimeError):
    pass


def _decode_rclone_config() -> str:
    encoded = os.environ.get("RCLONE_GDRIVE_CONF", "").strip()
    if not encoded:
        raise CallnotesError("RCLONE_GDRIVE_CONF is missing; run the Vault env helper first")
    try:
        return base64.b64decode(encoded, validate=True).decode()
    except Exception as exc:  # noqa: BLE001 - exact decoder errors differ by Python version
        raise CallnotesError("RCLONE_GDRIVE_CONF is not valid base64 text") from exc


@contextmanager
def temporary_rclone_env() -> Iterator[dict[str, str]]:
    """Write rclone config to a temp file and point RCLONE_CONFIG at it."""
    conf = _decode_rclone_config()
    with tempfile.TemporaryDirectory(prefix="callnotes-rclone-") as tmpdir:
        config_path = Path(tmpdir) / "rclone.conf"
        config_path.write_text(conf)
        config_path.chmod(0o600)
        env = os.environ.copy()
        env["RCLONE_CONFIG"] = str(config_path)
        yield env


def run_rclone(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = ["rclone", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)


def is_call_docx(name: str) -> bool:
    """Return true for Recorder docs named call.docx or call-prefixed .docx files."""
    normalized = name.strip().lower()
    return normalized == "call.docx" or (normalized.startswith("call") and normalized.endswith(".docx"))


def find_call_docs(*, env: dict[str, str]) -> list[str]:
    result = run_rclone(["lsjson", f"{REMOTE}:"], env=env)
    files = json.loads(result.stdout or "[]")
    docs = [f["Path"] for f in files if is_call_docx(f.get("Name", "")) and not f.get("IsDir")]
    print(f"Drive root scan: {len(files)} item(s), {len(docs)} call-prefixed .docx candidate(s).")
    return docs


def download_doc(remote_path: str, tmpdir: str, *, env: dict[str, str]) -> Path | None:
    run_rclone(["copy", f"{REMOTE}:{remote_path}", tmpdir], env=env)
    local = Path(tmpdir) / Path(remote_path).name
    return local if local.exists() else None


def extract_text(docx_path: Path) -> str:
    doc = Document(str(docx_path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _fallback_note(transcript: str) -> str:
    excerpt = transcript.strip()[:2000] or "N/A — empty transcript"
    return f"""---
date: {TODAY}
agent_readable: true
type: meeting_notes
account: ""
vendor: "[[SentinelOne]]"
product: "[[AI SIEM]]"
opportunity_id: "PLACEHOLDER"
acv: "PLACEHOLDER"
participants:
  - "[[Steve VanAllen]]"
tags:
  - meeting_notes
---
## 🦴 Big Goal
**One sentence:** Needs human review — generated without LLM assistance.

## 🎯 Command of the Message

| **Before Scenario (The Pain)** | **After Scenario (Positive Outcomes)** |
| :--- | :--- |
| Needs review | Needs review |

| **Required Capabilities & Metrics** | **S1 Differentiators & Proof Points** |
| :--- | :--- |
| Needs review | Needs review |

## 🏃 Action (To-Do)
- [ ] Review transcript and complete meeting note — Steve

## Transcript excerpt
{excerpt}
"""


def structure_note(transcript: str) -> str:
    if os.getenv("CALLNOTES_USE_LLM", "1").lower() in {"0", "false", "no"}:
        return _fallback_note(transcript)
    prompt = STRUCTURE_PROMPT.format(date=TODAY, transcript=transcript)
    try:
        return run_hermes_prompt(prompt, timeout=int(os.getenv("CALLNOTES_LLM_TIMEOUT", "300")), source="callnotes").strip()
    except Exception as exc:  # noqa: BLE001 - fallback is intentional automation behavior
        print(f"Hermes one-shot failed; writing review stub: {exc}")
        return _fallback_note(transcript)


def apply_name_aliases(note_md: str) -> str:
    for wrong, correct in NAME_ALIASES.items():
        note_md = note_md.replace(wrong, correct)
    return note_md


def ensure_fixed_participants(note_md: str) -> str:
    for link in FIXED_PARTICIPANTS:
        if link in note_md:
            continue
        updated = re.sub(
            r'(participants:\n(?:  - "?\[\[.*?\]\]"?\n)*)',
            lambda m: m.group(0) + f'  - "{link}"\n',
            note_md,
            count=1,
        )
        if updated == note_md:
            note_md += f'\n<!-- callnotes participant repair -->\nparticipants:\n  - "{link}"\n'
        else:
            note_md = updated
    return note_md


def derive_filename() -> str:
    # Account is intentionally blank in the note; preserve old date + Call pattern.
    return f"{OUTPUT_FOLDER}/{TODAY}-Call.md"


class ObsidianMCP:
    def __init__(self, url: str):
        self.url = url
        self.session_id = self._init()
        self._notify_initialized()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": self.session_id,
        }

    def _post(self, payload: dict[str, Any], *, stream: bool = False) -> requests.Response:
        response = requests.post(self.url, json=payload, headers=self._headers() if self.session_id else {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }, stream=stream, timeout=30)
        response.raise_for_status()
        return response

    def _init(self) -> str:
        response = requests.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "callnotes", "version": "2.0"},
                },
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            timeout=30,
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if not session_id:
            raise CallnotesError("obsidian-mcp did not return an MCP session id")
        return session_id

    def _notify_initialized(self) -> None:
        try:
            requests.post(
                self.url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers=self._headers(),
                timeout=10,
            )
        except Exception:
            pass

    @staticmethod
    def _parse_tool_response(response: requests.Response) -> dict[str, Any]:
        for line in response.iter_lines():
            if line and line.startswith(b"data: "):
                payload = json.loads(line[6:])
                if payload.get("error"):
                    raise CallnotesError(f"obsidian-mcp error: {payload['error']}")
                result = payload.get("result", {})
                if result.get("isError"):
                    raise CallnotesError(f"obsidian-mcp tool error: {result.get('content')}")
                return result
        raise CallnotesError("obsidian-mcp returned no tool result")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            stream=True,
        )
        return self._parse_tool_response(response)

    def write_file(self, path: str, content: str) -> None:
        self.call_tool("write_file", {"vault": VAULT, "path": path, "content": content})

    def verify_file(self, path: str) -> None:
        result = self.call_tool("read_file", {"vault": VAULT, "path": path})
        content = result.get("content", [])
        if not content:
            raise CallnotesError(f"obsidian-mcp read verification returned no content for {path}")


def check_runtime() -> int:
    print(f"callnotes runtime cwd={Path.cwd()}")
    print(f"target obsidian vault={VAULT_LABEL}/{OUTPUT_FOLDER}")
    if not shutil.which("rclone"):
        print("ERROR: rclone not found on PATH", file=sys.stderr)
        return 1
    if os.getenv("CALLNOTES_USE_LLM", "1").lower() not in {"0", "false", "no"} and not hermes_available():
        print("ERROR: hermes CLI not found on PATH", file=sys.stderr)
        return 1
    try:
        with temporary_rclone_env() as env:
            docs = find_call_docs(env=env)
        print(f"callnotes check ok; call.docx present={bool(docs)}")
        return 0
    except Exception as exc:  # noqa: BLE001 - check should summarize failure
        print(f"ERROR: callnotes check failed: {exc}", file=sys.stderr)
        return 1


def process_call_docs(*, dry_run: bool = False, keep_input: bool = False) -> int:
    with temporary_rclone_env() as rclone_env:
        call_docs = find_call_docs(env=rclone_env)
        if not call_docs:
            print("NO_INPUT: No 'call.docx' found in Drive root — nothing to do.")
            return 0

        print(f"Processing {len(call_docs)} file(s): {call_docs}")
        mcp = None if dry_run else ObsidianMCP(OBSIDIAN_MCP)
        written_paths: list[str] = []

        with tempfile.TemporaryDirectory(prefix="callnotes-docx-") as tmpdir:
            for remote_path in call_docs:
                local = download_doc(remote_path, tmpdir, env=rclone_env)
                if not local:
                    print(f"  Skipping {remote_path} — download failed")
                    continue
                transcript = extract_text(local)
                if not transcript:
                    print(f"  Skipping {remote_path} — empty transcript")
                    continue

                note_md = ensure_fixed_participants(apply_name_aliases(structure_note(transcript)))
                note_path = derive_filename()
                if dry_run:
                    print(f"  DRY_RUN: would write [{VAULT_LABEL}] {note_path} ({len(note_md)} chars)")
                else:
                    assert mcp is not None
                    mcp.write_file(note_path, note_md)
                    mcp.verify_file(note_path)
                    print(f"  NOTE_CREATED: [{VAULT_LABEL}] {note_path}")
                    written_paths.append(note_path)

        if dry_run:
            print("DRY_RUN: not deleting Drive input.")
            return 0
        if not written_paths:
            raise CallnotesError("no notes were written; refusing to delete Drive input")
        if keep_input:
            print("KEEP_INPUT: leaving Drive input in place by request.")
            return 0
        for path in call_docs:
            run_rclone(["delete", f"{REMOTE}:{path}"], env=rclone_env)
        print(f"Cleaned up {len(call_docs)} file(s) from Drive after verified note write.")
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Drive call.docx into sva-s1 meeting notes")
    parser.add_argument("--check", action="store_true", help="verify dependencies/secret/rclone access; no note write/delete")
    parser.add_argument("--dry-run", action="store_true", help="download/structure but do not write note or delete input")
    parser.add_argument("--no-llm", action="store_true", help="force deterministic fallback note structuring")
    parser.add_argument("--keep-input", action="store_true", help="after successful note write, do not delete call.docx")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.no_llm:
        os.environ["CALLNOTES_USE_LLM"] = "0"
    if args.check:
        return check_runtime()
    try:
        return process_call_docs(dry_run=args.dry_run, keep_input=args.keep_input)
    except Exception as exc:  # noqa: BLE001 - top-level automation summary
        print(f"ERROR: callnotes run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
