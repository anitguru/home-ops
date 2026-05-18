#!/usr/bin/env python3
"""
wiki_freshness.py — AnITGuru wiki source freshness verification.

Active scheduled runtime is the default-profile Hermes cron job
`Wiki freshness check`, launched from the home-ops repo. The weekly live path is
intentionally deterministic: `--dry-run --no-llm` checks source reachability and
delivers stdout; it does not call Gitea Actions, runners, Git push/writeback, or
direct Claude/Anthropic APIs.

Optional LLM drift analysis, when manually enabled, routes through
home-ops/hermes/scripts/hermes_llm.py so it uses subscription-backed Hermes
profiles instead of provider-specific SDKs or CLIs.

Vault access (auto-selected):
  Local: VAULT_ROOT env var or --vault path (used when path exists on disk)
  MCP:   OBSIDIAN_MCP_URL + OBSIDIAN_MCP_TOKEN (fallback when path absent)

Dry-run by default — no writes to wiki files.

Usage:
  python wiki_freshness.py [--dry-run] [--no-dry-run] [--limit N] [--vault PATH] [--no-llm]
"""

import asyncio
import argparse
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import httpx

HOME_OPS_HERMES_SCRIPTS = Path(os.environ.get(
    "HOME_OPS_HERMES_SCRIPTS",
    "/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts",
))
if str(HOME_OPS_HERMES_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOME_OPS_HERMES_SCRIPTS))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKIP_STEMS = {"README", "SCHEMA", "index", "log", "freshness-report"}

# ---------------------------------------------------------------------------
# Vault client abstraction
# ---------------------------------------------------------------------------

class VaultClient:
    def list_wiki_pages(self) -> list[str]:
        raise NotImplementedError
    def read_wiki_page(self, name: str) -> str:
        raise NotImplementedError
    def read_raw_file(self, rel_path: str) -> str | None:
        raise NotImplementedError
    def append_log(self, content: str) -> None:
        raise NotImplementedError


class LocalVaultClient(VaultClient):
    def __init__(self, root: Path):
        self.root     = root
        self.wiki_dir = root / "wiki"
        self.log_file = self.wiki_dir / "log.md"

    def list_wiki_pages(self) -> list[str]:
        return sorted(
            p.stem for p in self.wiki_dir.glob("*.md")
            if p.stem not in SKIP_STEMS
        )

    def read_wiki_page(self, name: str) -> str:
        return (self.wiki_dir / f"{name}.md").read_text(encoding="utf-8", errors="replace")

    def read_raw_file(self, rel_path: str) -> str | None:
        path = self.root / rel_path.lstrip("/")
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def append_log(self, content: str) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(content)


class ObsidianMCPClient(VaultClient):
    def __init__(self, url: str, token: str, vault: str = "personal"):
        self.url      = url.rstrip("/")
        self.token    = token
        self.vault    = vault
        self._next_id = 1
        self._session_id: str | None = None
        self._ssl_ctx = ssl._create_unverified_context()

    def _rpc(self, method: str, params: dict) -> object:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": self._next_id,
            "method": method, "params": params,
        }).encode()
        self._next_id += 1
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = urllib.request.Request(self.url, data=payload, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=60, context=self._ssl_ctx) as resp:
            if not self._session_id:
                self._session_id = resp.headers.get("mcp-session-id")
            body = resp.read().decode("utf-8", errors="replace")
        return self._parse(body)

    def _parse(self, body: str) -> object:
        body = body.strip()
        if body.startswith("{"):
            data = json.loads(body)
        else:
            for line in body.splitlines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    break
            else:
                raise ValueError(f"unparseable MCP response: {body[:120]}")
        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("result")

    def _initialize(self) -> None:
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "wiki-freshness", "version": "1.0"},
        })

    def _tool(self, name: str, arguments: dict) -> object:
        if not self._session_id:
            self._initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", []) if isinstance(result, dict) else []
        if content and content[0].get("type") == "text":
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return result

    # Backwards-compatible test seam used by the unit tests.
    def call_tool(self, name: str, arguments: dict) -> object:
        return self._tool(name, arguments)

    def list_files(self, path: str) -> list[str]:
        result = self.call_tool("list_files", {"vault": self.vault, "path": path})
        if isinstance(result, str):
            return [ln.strip() for ln in result.splitlines() if ln.strip()]
        if isinstance(result, list):
            return [str(x) for x in result]
        return []

    def list_wiki_pages(self) -> list[str]:
        # list_files returns only 1 result; use search instead.
        # Every wiki page contains "**Summary**" — returns one content item per match.
        if not self._session_id:
            self._initialize()
        result = self._rpc("tools/call", {
            "name": "search",
            "arguments": {"vault": self.vault, "query": "**Summary**", "path": "wiki"},
        })
        content = result.get("content", []) if isinstance(result, dict) else []
        stems = set()
        for item in content:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            try:
                obj = json.loads(text)
                fp  = obj.get("file", "")
            except (json.JSONDecodeError, AttributeError):
                import re as _re
                m = _re.search(r'"file":\s*"([^"]+)"', text)
                fp = m.group(1) if m else ""
            if fp:
                stem = Path(fp).stem
                if stem not in SKIP_STEMS:
                    stems.add(stem)
        return sorted(stems)

    def read_wiki_page(self, name: str) -> str:
        return str(self._tool("read_file", {"vault": self.vault, "path": f"wiki/{name}.md"}))

    def read_raw_file(self, rel_path: str) -> str | None:
        try:
            return str(self._tool("read_file", {"vault": self.vault, "path": rel_path.lstrip("/")}))
        except Exception:
            return None

    def append_log(self, content: str) -> None:
        self._tool("append_file", {"vault": self.vault, "path": "wiki/log.md", "content": content})


def make_client(vault_arg: str | None) -> VaultClient:
    vault_root = (
        vault_arg
        or os.getenv("VAULT_ROOT")
        or os.getenv("WIKI_PATH")
        or "/Users/sva/Documents/Dropbox/Obsidian/AnITGuru"
    )
    if Path(vault_root).exists():
        return LocalVaultClient(Path(vault_root))
    url   = os.getenv("OBSIDIAN_MCP_URL")
    token = os.getenv("OBSIDIAN_MCP_TOKEN")
    vault = os.getenv("OBSIDIAN_MCP_VAULT", "personal")
    if not url or not token:
        raise SystemExit(
            f"Vault path {vault_root!r} not found and "
            "OBSIDIAN_MCP_URL / OBSIDIAN_MCP_TOKEN not set."
        )
    print(f"[wiki-freshness] vault path absent — using Obsidian MCP ({url})")
    return ObsidianMCPClient(url, token, vault)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sources(text: str) -> list[str]:
    """Extract normalized _raw source refs from a wiki page Sources line."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("**Sources**:"):
            continue
        raw = stripped[len("**Sources**:"):].strip()
        parts = re.split(r"[,;]", raw)
        out = []
        for part in parts:
            m = re.search(r'\[[^\]]+\]\((.*?)\)', part)
            src = m.group(1) if m else part
            src = urllib.parse.unquote(src.strip().strip("`"))
            if src:
                out.append(src)
        return out
    return []


def extract_source_url(text: str) -> str | None:
    """Prefer frontmatter url/source, then fall back to first URL in body."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if m:
        fm = m.group(1)
        for key in ("url", "source"):
            for line in fm.splitlines():
                if re.match(rf"^{key}\s*:", line):
                    url = line.partition(":")[2].strip().strip('"').strip("'")
                    if url.startswith("http"):
                        return url
    m = re.search(r"https?://[^\s)>'\"]+", text)
    return m.group(0) if m else None


def parse_wiki_page(name: str, text: str) -> dict:
    result = {
        "name":         name,
        "summary":      "",
        "sources":      [],
        "confidence":   None,
        "last_updated": None,
        "content":      text,
    }
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Summary**:"):
            result["summary"] = stripped[len("**Summary**:"):].strip()
        elif stripped.startswith("**Sources**:"):
            result["sources"] = parse_sources(text)
        elif stripped.startswith("**Confidence**:"):
            val = stripped[len("**Confidence**:"):].strip().split()[0]
            try:
                result["confidence"] = int(val)
            except ValueError:
                result["confidence"] = 1
        elif stripped.startswith("**Last updated**:"):
            result["last_updated"] = stripped[len("**Last updated**:"):].strip()
    return result


def source_url_from_raw(client: VaultClient, src_ref: str) -> str | None:
    text = client.read_raw_file(src_ref)
    if not text:
        return None
    return extract_source_url(text)


def build_inventory(client: VaultClient) -> dict:
    pages = client.list_wiki_pages()
    sources = []
    pages_meta = []
    missing = []
    seen = set()
    for name in pages:
        page = parse_wiki_page(name, client.read_wiki_page(name))
        pages_meta.append({"name": name, "path": f"wiki/{name}.md", "sources": page["sources"], "confidence": page["confidence"]})
        for src in page["sources"]:
            raw = client.read_raw_file(src)
            if raw is None:
                missing.append({"page": name, "source": src})
                continue
            if src not in seen:
                seen.add(src)
                sources.append({"path": src, "url": extract_source_url(raw), "status": "unchecked", "http_status": None})
    return {
        "page_count": len(pages),
        "source_count": len(sources),
        "pages": pages_meta,
        "missing_source_refs": missing,
        "sources": sources,
    }


def render_markdown_report(report: dict) -> str:
    lines = [
        "# Wiki Freshness Report",
        "",
        f"Pages scanned: {report.get('page_count', 0)}",
        f"Sources scanned: {report.get('source_count', 0)}",
        f"Missing source refs: {len(report.get('missing_source_refs', []))}",
        "",
        "## Sources",
        "",
        "| Source | URL | Status | HTTP |",
        "|---|---|---|---|",
    ]
    for src in report.get("sources", []):
        lines.append(
            f"| `{src.get('path','')}` | {src.get('url') or ''} | {src.get('status') or ''} | {src.get('http_status') or ''} |"
        )
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

async def head_check(client: httpx.AsyncClient, url: str) -> tuple[int, str]:
    try:
        r = await client.head(url, follow_redirects=True, timeout=10)
        return r.status_code, "ok" if r.status_code < 400 else f"http_{r.status_code}"
    except httpx.TimeoutException:
        return 0, "timeout"
    except Exception as e:
        return 0, str(e)[:60]


async def fetch_page(client: httpx.AsyncClient, url: str, max_chars: int = 4000) -> str:
    try:
        r = await client.get(
            url, follow_redirects=True, timeout=15,
            headers={"User-Agent": "wiki-freshness/1.0 (homelab bot)"},
        )
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Optional Hermes analysis
# ---------------------------------------------------------------------------

def _llm_call(prompt: str, *, source: str, timeout: int = 180) -> str:
    # Lazy import so the deterministic --no-llm scheduled path has no Hermes
    # subprocess dependency beyond the cron launcher itself.
    from hermes_llm import run_hermes_prompt

    return run_hermes_prompt(prompt, timeout=timeout, source=source)


def quick_triage(summary: str, url: str, snippet: str) -> dict:
    prompt = (
        f"Wiki summary: {summary}\n\n"
        f"Source URL: {url}\n"
        f"Current page snippet:\n{snippet[:600]}\n\n"
        "Has the source content materially changed from what the wiki summary describes?\n"
        'Respond with JSON only, no other text: {"drifted": true|false, "reason": "one sentence"}'
    )
    try:
        return json.loads(_llm_call(prompt, source="wiki-freshness-triage", timeout=180))
    except Exception:
        return {"drifted": False, "reason": "parse error"}


def deep_analysis(page_excerpt: str, url: str, current: str) -> dict:
    prompt = (
        f"Review this wiki page excerpt for staleness against the current source.\n\n"
        f"Wiki excerpt:\n{page_excerpt[:2000]}\n\n"
        f"Current source ({url}):\n{current[:3000]}\n\n"
        "Are the key technical claims still accurate?\n\n"
        "Return JSON only, no other text:\n"
        '{"verdict": "accurate"|"minor_drift"|"major_drift"|"stale", '
        '"confidence_action": "maintain"|"downgrade_1"|"downgrade_to_1", '
        '"summary": "2-3 sentences", '
        '"key_changes": ["change1"]}'
    )
    try:
        raw = _llm_call(prompt, source="wiki-freshness-deep", timeout=240)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
        raise ValueError(f"no JSON in output: {raw[:200]}")
    except Exception as exc:
        print(f"\n    [deep-analysis parse error] {exc}", file=sys.stderr)
        return {
            "verdict": "unknown",
            "confidence_action": "maintain",
            "summary": f"parse error: {str(exc)[:80]}",
            "key_changes": [],
        }

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run(dry_run: bool, limit: int | None, client: VaultClient, use_llm: bool = True) -> list[dict]:
    pages = client.list_wiki_pages()
    if limit:
        pages = pages[:limit]

    mode = "DRY RUN" if dry_run else "LIVE"
    backend = "local" if isinstance(client, LocalVaultClient) else "MCP"
    analysis_mode = "LLM drift analysis" if use_llm else "no-LLM reachability audit"
    print(f"[wiki-freshness] {mode} — {len(pages)} pages — backend: {backend} — {analysis_mode}")
    if use_llm:
        print("  Optional Hermes drift analysis enabled.\n")
    else:
        print("  LLM calls disabled; checking source URLs only.\n")

    report: list[dict] = []

    async with httpx.AsyncClient() as http:
        for name in pages:
            text = client.read_wiki_page(name)
            page = parse_wiki_page(name, text)
            entry = {
                "page":              name,
                "confidence":        page["confidence"],
                "verdict":           "ok",
                "confidence_action": "maintain",
                "details":           [],
            }

            url = None
            for src_ref in page["sources"]:
                url = source_url_from_raw(client, src_ref)
                if url:
                    break

            if not url:
                entry["verdict"] = "no_url"
                entry["note"]    = "No source URL in _raw/ frontmatter"
                report.append(entry)
                print(f"  [{name}] no_url — skipping")
                continue

            status, desc = await head_check(http, url)
            entry["url"]         = url
            entry["http_status"] = status

            if status == 0 or status >= 400:
                entry["verdict"]           = "dead_url"
                entry["confidence_action"] = "downgrade_to_1"
                entry["note"]              = f"HTTP {status}: {desc}"
                report.append(entry)
                print(f"  [{name}] dead_url  {status} {url[:70]}")
                continue

            print(f"  [{name}] live ({status})  ", end="", flush=True)

            if not use_llm:
                entry["verdict"] = "source_reachable"
                entry["note"] = "LLM drift analysis disabled"
                print("source_reachable  (LLM disabled)")
                report.append(entry)
                continue

            snippet = await fetch_page(http, url)
            triage = quick_triage(page["summary"], url, snippet)
            entry["triage"] = triage

            if not triage.get("drifted"):
                entry["verdict"] = "ok"
                print(f"ok  (triage: {triage['reason'][:60]})")
                report.append(entry)
                continue

            print("DRIFT flagged  ", end="", flush=True)

            deep = deep_analysis(page["content"], url, snippet)
            entry["deep_analysis"]      = deep
            entry["verdict"]           = deep["verdict"]
            entry["confidence_action"] = deep["confidence_action"]
            print(f"{deep['verdict']}  {deep['summary'][:70]}")
            report.append(entry)

    counts = {}
    for e in report:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1

    print(f"\n{'─'*60}")
    print(f"Results: {json.dumps(counts)}")

    needs_attention = [e for e in report if e["verdict"] not in ("ok", "no_url", "accurate", "source_reachable")]
    if needs_attention:
        print("\nNeeds attention:")
        for e in needs_attention:
            note = e.get("deep_analysis", {}).get("summary") or e.get("note", "")
            print(f"  {e['page']}  [{e['verdict']}]  action={e.get('confidence_action','')}")
            if note:
                print(f"    → {note[:100]}")

    if not dry_run and needs_attention:
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = f"\n## Freshness check — {ts}\n"
        for e in needs_attention:
            note     = e.get("deep_analysis", {}).get("summary") or e.get("note", "")
            content += (
                f"- **{e['page']}**: {e['verdict']} ({e.get('confidence_action','')})"
                + (f" — {note}" if note else "") + "\n"
            )
        client.append_log(content)
        print(f"\nAppended {len(needs_attention)} entries to wiki/log.md")
    elif dry_run:
        print("\nDry run — no files written.")

    return report


def main():
    parser = argparse.ArgumentParser(description="Wiki freshness checker")
    parser.add_argument("--dry-run",    action="store_true",  default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--limit",  type=int,  default=None)
    parser.add_argument("--vault",  default=None, help="Vault root path (local mode)")
    parser.add_argument(
        "--no-llm",
        dest="use_llm",
        action="store_false",
        default=os.getenv("WIKI_FRESHNESS_USE_LLM", "1").lower() not in {"0", "false", "no"},
        help="Disable LLM drift analysis and only check source URL reachability",
    )
    args = parser.parse_args()

    client = make_client(args.vault)
    asyncio.run(run(args.dry_run, args.limit, client, use_llm=args.use_llm))


if __name__ == "__main__":
    main()
