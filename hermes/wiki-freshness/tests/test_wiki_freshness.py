import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wiki_freshness as wf


def test_parse_sources_line_handles_comma_markdown_links_and_paths():
    text = """# Example
**Sources**: _raw/one.md, `_raw/two.md`; [_raw/three file.md](_raw/three%20file.md)
**Confidence**: 2
"""

    assert wf.parse_sources(text) == [
        "_raw/one.md",
        "_raw/two.md",
        "_raw/three file.md",
    ]


def test_extract_source_url_prefers_frontmatter_url():
    text = """---
url: https://example.com/frontmatter
source: https://example.com/source
---
Body https://example.com/body
"""

    assert wf.extract_source_url(text) == "https://example.com/frontmatter"


def test_extract_source_url_falls_back_to_first_body_url():
    text = "Captured from https://example.com/article?x=1 and mirrored."

    assert wf.extract_source_url(text) == "https://example.com/article?x=1"


def test_obsidian_mcp_list_files_splits_newline_text_response():
    client = wf.ObsidianMCPClient("https://example.invalid/mcp", "token")
    client.call_tool = lambda name, args: "wiki/a.md\nwiki/b.md\n"  # type: ignore[method-assign]

    assert client.list_files("wiki") == ["wiki/a.md", "wiki/b.md"]


def test_inventory_local_vault_maps_pages_to_sources(tmp_path):
    vault = tmp_path
    (vault / "wiki").mkdir()
    (vault / "_raw").mkdir()
    (vault / "wiki" / "example.md").write_text(
        "# Example\n**Sources**: _raw/source.md\n**Confidence**: 2\n",
        encoding="utf-8",
    )
    (vault / "_raw" / "source.md").write_text(
        "---\nurl: https://example.com/source\n---\nraw",
        encoding="utf-8",
    )

    report = wf.build_inventory(wf.LocalVaultClient(vault))

    assert report["page_count"] == 1
    assert report["source_count"] == 1
    assert report["pages"][0]["path"] == "wiki/example.md"
    assert report["sources"][0]["url"] == "https://example.com/source"


def test_render_markdown_report_includes_counts_and_statuses():
    report = {
        "page_count": 1,
        "source_count": 1,
        "missing_source_refs": [],
        "sources": [{"path": "_raw/source.md", "url": "https://example.com", "status": "live", "http_status": 200}],
    }

    rendered = wf.render_markdown_report(report)

    assert "# Wiki Freshness Report" in rendered
    assert "Pages scanned: 1" in rendered
    assert "_raw/source.md" in rendered
    assert "live" in rendered
