#!/usr/bin/env python3
"""
rss_ingest.py — RSS-triggered wiki ingest pipeline

Modes:
  --url URL     Ingest a single URL (pilot / one-off)
  --rss         Poll configured RSS feed for new items

Scrapers (auto-selected by env):
  Firecrawl:  FIRECRAWL_URL  (preferred, self-hosted at iaconcity)
  Tavily:     TAVILY_API_KEY (cloud fallback)

Vault access (auto-selected):
  Local:  VAULT_ROOT env or --vault path
  MCP:    OBSIDIAN_MCP_URL + OBSIDIAN_MCP_TOKEN

_raw/ lifecycle:
  _raw/{slug}.md          status: pending   (written on fetch)
  _raw/{slug}.md          status: processed (updated after wiki synthesis)
  _raw/processed/{slug}.md                  (copy, canonical "done" marker)

Usage:
  python rss_ingest.py --url https://docs.astro.build/en/basics/project-structure/ [--dry-run]
  python rss_ingest.py --rss --limit 3 [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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

DEFAULT_FEED  = "https://astro.build/rss.xml"
STATE_PATH    = "_agent/state/rss-astro.json"

# ---------------------------------------------------------------------------
# Vault client
# ---------------------------------------------------------------------------

class VaultClient:
    def read_file(self, path: str) -> str | None:       raise NotImplementedError
    def write_file(self, path: str, content: str):      raise NotImplementedError
    def append_file(self, path: str, content: str):     raise NotImplementedError
    def file_exists(self, path: str) -> bool:           return self.read_file(path) is not None


class LocalVaultClient(VaultClient):
    def __init__(self, root: Path):
        self.root = root

    def _p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def read_file(self, path: str) -> str | None:
        p = self._p(path)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_file(self, path: str, content: str) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def append_file(self, path: str, content: str) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)


class ObsidianMCPClient(VaultClient):
    def __init__(self, url: str, token: str, vault: str = "personal"):
        self.url      = url.rstrip("/")
        self.token    = token
        self.vault    = vault
        self._nid     = 1
        self._sid: str | None = None
        self._ssl     = ssl._create_unverified_context()

    def _rpc(self, method: str, params: dict) -> object:
        payload = json.dumps({"jsonrpc": "2.0", "id": self._nid,
                               "method": method, "params": params}).encode()
        self._nid += 1
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._sid:
            headers["Mcp-Session-Id"] = self._sid
        req = urllib.request.Request(self.url, data=payload, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=60, context=self._ssl) as r:
            if not self._sid:
                self._sid = r.headers.get("mcp-session-id")
            body = r.read().decode("utf-8", errors="replace")
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

    def _init(self) -> None:
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "rss-ingest", "version": "1.0"}})

    def _tool(self, name: str, args: dict) -> object:
        if not self._sid:
            self._init()
        result  = self._rpc("tools/call", {"name": name, "arguments": args})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(f"MCP tool error: {result}")
        content = result.get("content", []) if isinstance(result, dict) else []
        if content and content[0].get("type") == "text":
            text = content[0]["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return result

    def read_file(self, path: str) -> str | None:
        try:
            result = self._tool("read_file", {"vault": self.vault, "path": path.lstrip("/")})
            return str(result) if result is not None else None
        except Exception:
            return None

    def write_file(self, path: str, content: str) -> None:
        self._tool("write_file", {"vault": self.vault, "path": path.lstrip("/"), "content": content})

    def append_file(self, path: str, content: str) -> None:
        self._tool("append_file", {"vault": self.vault, "path": path.lstrip("/"), "content": content})


def make_client(vault_arg: str | None = None) -> VaultClient:
    vault_root = vault_arg or os.getenv("VAULT_ROOT", "/home/pi/app/obsidian-personal")
    if Path(vault_root).exists():
        return LocalVaultClient(Path(vault_root))
    url   = os.getenv("OBSIDIAN_MCP_URL")
    token = os.getenv("OBSIDIAN_MCP_TOKEN")
    vault = os.getenv("OBSIDIAN_MCP_VAULT", "personal")
    if not url or not token:
        raise SystemExit(f"Vault path {vault_root!r} not found and OBSIDIAN_MCP_URL/TOKEN not set.")
    print(f"[rss-ingest] vault path absent — using Obsidian MCP")
    return ObsidianMCPClient(url, token, vault)

def list_wiki_slugs(vault: VaultClient) -> set[str]:
    if isinstance(vault, LocalVaultClient):
        wiki_dir = vault.root / "wiki"
        return {p.stem for p in wiki_dir.glob("*.md")} if wiki_dir.exists() else set()
    if not vault._sid:
        vault._init()
    result = vault._rpc("tools/call", {
        "name": "search",
        "arguments": {"vault": vault.vault, "query": "**Summary**", "path": "wiki"},
    })
    content = result.get("content", []) if isinstance(result, dict) else []
    slugs: set[str] = set()
    for item in content:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        try:
            fp = json.loads(text).get("file", "")
        except (json.JSONDecodeError, AttributeError):
            m = re.search(r'"file":\s*"([^"]+)"', text)
            fp = m.group(1) if m else ""
        if fp:
            slugs.add(Path(fp).stem)
    return slugs

# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def fetch_content(url: str) -> str:
    """Return clean markdown. Tries Firecrawl first, falls back to Tavily."""
    firecrawl_url = os.getenv("FIRECRAWL_URL")
    tavily_key    = os.getenv("TAVILY_API_KEY")

    if firecrawl_url:
        try:
            result = _firecrawl(firecrawl_url, url)
            print(f"  [scraper] firecrawl ✓")
            return result
        except Exception as e:
            print(f"  [scraper] firecrawl failed ({e}) — falling back to Tavily")

    if tavily_key:
        result = _tavily(tavily_key, url)
        print(f"  [scraper] tavily ✓")
        return result

    raise RuntimeError("No scraper configured. Set FIRECRAWL_URL or TAVILY_API_KEY.")


def _firecrawl(base_url: str, url: str) -> str:
    payload = json.dumps({
        "url": url, "formats": ["markdown"],
        "excludeTags": ["nav", "footer", "header", ".sidebar", ".toc"],
        "waitFor": 1000,
    }).encode()
    headers = {"Content-Type": "application/json"}
    token = os.getenv("FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/scrape", data=payload,
        method="POST", headers=headers,
    )
    cafile = os.getenv("FIRECRAWL_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
    context = ssl.create_default_context(cafile=cafile) if cafile else None
    with urllib.request.urlopen(req, timeout=30, context=context) as r:
        data = json.loads(r.read())
    if not data.get("success"):
        raise RuntimeError(f"Firecrawl: {data}")
    return data["data"]["markdown"]


def _tavily(api_key: str, url: str) -> str:
    payload = json.dumps({"urls": [url], "api_key": api_key}).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/extract", data=payload,
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = data.get("results", [])
    if not results:
        raise RuntimeError(f"Tavily: no results for {url}")
    return results[0].get("raw_content", "")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def url_to_title(segment: str) -> str:
    """Convert a URL path segment to a readable title, handling camelCase and kebab-case."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", segment)  # camelCase → camel Case
    return spaced.replace("-", " ").title()


def url_to_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path   = parsed.path.rstrip("/")
    parts  = [p for p in path.split("/") if p and p not in ("en", "www")]
    slug   = "-".join(parts).lower()
    slug   = re.sub(r"[^a-z0-9-]", "-", slug)
    slug   = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


_SITE_INDEX = {
    "docs.astro.build":   ("## Web Frameworks", "### Astro"),
    "astro.build":        ("## Astro Blog", None),
    "tailwindcss.com":    ("## CSS Frameworks", "### Tailwind CSS"),
    "typescriptlang.org": ("## Languages", "### TypeScript"),
    "react.dev":          ("## Web Frameworks", "### React"),
}

def url_to_index_section(url: str) -> tuple[str, str | None]:
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    for domain, mapping in _SITE_INDEX.items():
        if domain in host:
            return mapping
    return f"## {host.split('.')[0].title()}", None


def append_to_index(index: str, section: str, subsection: str | None, entry: str) -> str:
    lines = index.splitlines()

    sec_idx = next((i for i, l in enumerate(lines) if l.strip() == section), -1)

    if sec_idx == -1:
        tail = f"\n\n{section}\n"
        if subsection:
            tail += f"\n{subsection}\n"
        tail += f"\n{entry}"
        return index.rstrip() + tail + "\n"

    if subsection:
        sub_idx = -1
        for i in range(sec_idx + 1, len(lines)):
            if lines[i].startswith("## "):
                break
            if lines[i].strip() == subsection:
                sub_idx = i
                break
        if sub_idx == -1:
            # find end of section
            end = next((i for i in range(sec_idx + 1, len(lines))
                        if lines[i].startswith("## ")), len(lines))
            lines[end:end] = ["", subsection, "", entry]
            return "\n".join(lines) + "\n"
        # insert after last bullet in subsection
        ins = sub_idx + 1
        while ins < len(lines) and (lines[ins].startswith("- ") or not lines[ins].strip()):
            ins += 1
        lines.insert(ins, entry)
    else:
        ins = sec_idx + 1
        while ins < len(lines) and (lines[ins].startswith("- ") or not lines[ins].strip()):
            ins += 1
        lines.insert(ins, entry)

    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

_PROMPT = """\
You are writing a structured Obsidian wiki page from raw scraped web content.

Source URL: {url}
Title: {title}

Raw content:
{content}

Write the wiki page in EXACTLY this format — output only the page, no commentary:

# {title}

**Summary**: <1-2 sentences capturing the key technical claims>
**Sources**: [{raw_path}]({raw_path})
**Confidence**: 3
**Last updated**: {date}

---

<Synthesized technical content. Rules:
- Preserve directory trees in ```markdown-tree``` fenced blocks with tab-indented hierarchy (strip any existing box-drawing chars ├ └ │ and convert to clean indentation)
- Convert callout prefixes to Obsidian native callout syntax:
    Tip / Hint        → > [!TIP]\n> content
    Note / Info       → > [!NOTE]\n> content
    Important         → > [!IMPORTANT]\n> content
    Warning / Caution → > [!WARNING]\n> content
    Danger / Error    → > [!DANGER]\n> content
- Keep code examples in fenced blocks with the original language tag
- Remove navigation links, breadcrumb text, "Section titled" anchors, footer links
- Write in present tense, factual and concise>
"""


def synthesize(content: str, url: str, title: str, raw_path: str) -> str:
    date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if os.getenv("RSS_INGEST_USE_LLM", "1").lower() in {"0", "false", "no"}:
        excerpt = re.sub(r"\s+", " ", content).strip()[:1200]
        return f"""# {title}

**Summary**: Needs human review — synthesized without LLM assistance.
**Sources**: [{raw_path}]({raw_path})
**Confidence**: 2
**Last updated**: {date}

---

Source: {url}

## Extracted excerpt

{excerpt}
""".strip()
    prompt = _PROMPT.format(
        url=url, title=title, content=content[:6000],
        raw_path=raw_path, date=date,
    )
    result = run_hermes_prompt(prompt, timeout=300, source="rss-ingest-synthesis")
    out = result.strip()
    out = re.sub(r"^```[a-z]*\n?", "", out)
    out = re.sub(r"\n?```$",       "", out)
    return out.strip()

# ---------------------------------------------------------------------------
# Core: ingest one URL
# ---------------------------------------------------------------------------

def ingest_url(url: str, title: str, feed_url: str,
               vault: VaultClient, dry_run: bool, force: bool = False) -> bool:
    slug           = url_to_slug(url)
    raw_path       = f"_raw/{slug}.md"
    processed_path = f"_raw/processed/{slug}.md"
    wiki_path      = f"wiki/{slug}.md"

    if not force and (vault.file_exists(processed_path) or vault.file_exists(wiki_path)):
        print(f"  [{slug}] already ingested — skipping (use --force to re-ingest)")
        return False

    print(f"  [{slug}] fetching...")
    try:
        content = fetch_content(url)
    except Exception as e:
        print(f"  [{slug}] FETCH ERROR: {e}")
        return False
    print(f"  [{slug}] {len(content)} chars — synthesizing with Hermes...")

    now = datetime.now(timezone.utc).isoformat()
    raw_text = (
        f"---\nsource: {url}\ntitle: {title}\n"
        f"feed: {feed_url}\nfetched_at: {now}\nstatus: pending\n---\n\n"
        + content
    )

    try:
        wiki_text = synthesize(content, url, title, raw_path)
    except Exception as e:
        print(f"  [{slug}] SYNTHESIS ERROR: {e}")
        return False

    # Extract summary for index entry
    summary = next(
        (l[len("**Summary**:"):].strip() for l in wiki_text.splitlines()
         if l.startswith("**Summary**:")),
        title,
    )

    if dry_run:
        print(f"  [{slug}] DRY RUN — would write {raw_path} + {wiki_path}")
        print(f"    Summary: {summary[:100]}")
        return True

    # Write _raw/ (pending → will be updated to processed below)
    vault.write_file(raw_path, raw_text)

    # Write wiki/
    vault.write_file(wiki_path, wiki_text)

    # Write _raw/processed/ (canonical done marker) + update status in _raw/
    processed_text = raw_text.replace("status: pending", "status: processed", 1)
    vault.write_file(processed_path, processed_text)
    vault.write_file(raw_path, processed_text)

    # Update wiki/index.md
    section, subsection = url_to_index_section(url)
    index = vault.read_file("wiki/index.md") or ""
    vault.write_file("wiki/index.md",
                     append_to_index(index, section, subsection,
                                     f"- [[{slug}]] - {summary}"))

    # Append to wiki/log.md
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vault.append_file("wiki/log.md",
                      f"\n- {ts}: Ingested [{title}]({wiki_path}) from {url}\n")

    print(f"  [{slug}] done ✓")
    return True

# ---------------------------------------------------------------------------
# RSS polling
# ---------------------------------------------------------------------------

def poll_rss(feed_url: str, state_path: str,
             vault: VaultClient, dry_run: bool, limit: int | None,
             force: bool = False) -> list[str]:
    raw_state = vault.read_file(state_path) or '{"seen_guids":[]}'
    try:
        state = json.loads(raw_state)
    except Exception:
        state = {"seen_guids": []}
    seen = set(state.get("seen_guids", []))

    print(f"[rss-ingest] fetching {feed_url}")
    req = urllib.request.Request(feed_url, headers={"User-Agent": "rss-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rss = r.read().decode("utf-8", errors="replace")

    items = []
    for m in re.finditer(r"<item>(.*?)</item>", rss, re.DOTALL):
        xml = m.group(1)

        def get(tag: str) -> str:
            t = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>",
                          xml, re.DOTALL)
            return t.group(1).strip() if t else ""

        guid  = get("guid") or get("link")
        title = get("title")
        link  = get("link")
        if guid and guid not in seen:
            items.append({"guid": guid, "title": title, "link": link})

    print(f"[rss-ingest] {len(items)} new items ({len(seen)} already seen)")
    if limit:
        items = items[:limit]

    ingested: list[str] = []
    for item in items:
        ok = ingest_url(item["link"], item["title"], feed_url, vault, dry_run, force)
        if ok and not dry_run:
            seen.add(item["guid"])
            ingested.append(item["guid"])

    if not dry_run and ingested:
        state["seen_guids"]   = list(seen)
        state["last_checked"] = datetime.now(timezone.utc).isoformat()
        vault.write_file(state_path, json.dumps(state, indent=2) + "\n")
        print(f"[rss-ingest] state saved ({len(seen)} seen GUIDs)")

    return ingested

# ---------------------------------------------------------------------------
# Wishlist / site crawl
# ---------------------------------------------------------------------------

def fetch_sitemap_urls(sitemap_url: str, filter_prefix: str) -> list[str]:
    req = urllib.request.Request(sitemap_url, headers={"User-Agent": "docs-crawl/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        xml = r.read().decode("utf-8", errors="replace")
    return [u for u in re.findall(r"<loc>(.*?)</loc>", xml)
            if urllib.parse.urlparse(u).path.startswith(filter_prefix)]


def load_site_urls(site: dict) -> list[str]:
    if "sitemap" in site:
        return fetch_sitemap_urls(site["sitemap"], site["filter"])
    list_path = Path(site["urllist"])
    if not list_path.exists():
        raise FileNotFoundError(f"URL list not found: {list_path}")
    base = site.get("base_url", "").rstrip("/")
    paths = [l.strip() for l in list_path.read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    return [f"{base}{p}" for p in paths]


def run_wishlist(site_name: str, sites_cfg: list[dict],
                 vault: VaultClient, dry_run: bool, force: bool, cap: int) -> int:
    site = next((s for s in sites_cfg if s["name"] == site_name), None)
    if site is None:
        names = [s["name"] for s in sites_cfg]
        raise SystemExit(f"Unknown site {site_name!r}. Available: {names}")

    print(f"[wishlist:{site_name}] discovering URLs...")
    all_urls = load_site_urls(site)
    print(f"[wishlist:{site_name}] {len(all_urls)} total source URLs")

    print(f"[wishlist:{site_name}] listing existing wiki slugs...")
    existing = list_wiki_slugs(vault)
    print(f"[wishlist:{site_name}] {len(existing)} pages already in wiki")

    missing = [u for u in all_urls if url_to_slug(u) not in existing]
    print(f"[wishlist:{site_name}] {len(missing)} missing — ingesting up to {cap}")

    if not missing:
        print(f"[wishlist:{site_name}] complete ✓")
        return 0

    feed_ref = site.get("sitemap", site.get("base_url", ""))
    ingested = 0
    for url in missing[:cap]:
        title = url_to_title(url.rstrip("/").split("/")[-1])
        if ingest_url(url, title, feed_ref, vault, dry_run, force):
            ingested += 1

    print(f"[wishlist:{site_name}] ingested {ingested} pages this run")
    return ingested

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RSS-triggered wiki ingest pipeline")
    parser.add_argument("--url",   help="Ingest a single URL directly")
    parser.add_argument("--title", help="Override title for --url mode")
    parser.add_argument("--rss",   action="store_true", help="Poll RSS feed")
    parser.add_argument("--feed",  default=DEFAULT_FEED)
    parser.add_argument("--state", default=STATE_PATH)
    parser.add_argument("--vault", default=None, help="Override vault root path")
    parser.add_argument("--dry-run",    dest="dry_run", action="store_true",  default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--force",  action="store_true", default=False,
                        help="Re-ingest even if wiki/ or _raw/processed/ already exists")
    parser.add_argument("--limit",  type=int, default=None)
    parser.add_argument("--wishlist", metavar="SITE",
                        help="Ingest missing pages for SITE defined in --sites-config")
    parser.add_argument("--sites-config", default="scripts/docs-sites.json",
                        help="Path to docs-sites.json")
    parser.add_argument("--cap", type=int, default=5,
                        help="Max pages to ingest per wishlist run (default 5)")
    args = parser.parse_args()

    vault = make_client(args.vault)
    mode  = "DRY RUN" if args.dry_run else "LIVE"
    print(f"[rss-ingest] {mode}{' FORCE' if args.force else ''}")

    if args.url:
        title = args.title or url_to_title(args.url.rstrip("/").split("/")[-1])
        ingest_url(args.url, title, args.feed, vault, args.dry_run, args.force)
    elif args.rss:
        poll_rss(args.feed, args.state, vault, args.dry_run, args.limit, args.force)
    elif args.wishlist:
        cfg_path = Path(args.sites_config)
        if not cfg_path.exists():
            raise SystemExit(f"Sites config not found: {cfg_path}")
        sites_cfg = json.loads(cfg_path.read_text())
        run_wishlist(args.wishlist, sites_cfg, vault, args.dry_run, args.force, args.cap)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
