import json
import sys
from pathlib import Path

import pytest

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


def test_extract_source_url_accepts_schema_source_url():
    text = """---
source_url: https://example.com/schema-field
---
Body
"""

    assert wf.extract_source_url(text) == "https://example.com/schema-field"


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


def test_current_40_wiki_layout_recurses_and_reads_direct_source_frontmatter(tmp_path):
    capture = tmp_path / "40-wiki" / "raw" / "docs" / "example.md"
    capture.parent.mkdir(parents=True)
    capture.write_text(
        "---\nsource: https://example.com/current\nstatus: processed\n---\n# Current capture\n",
        encoding="utf-8",
    )
    (tmp_path / "40-wiki" / "services").mkdir()
    (tmp_path / "40-wiki" / "services" / "note.md").write_text(
        "# Note without a canonical source\n",
        encoding="utf-8",
    )

    client = wf.LocalVaultClient(tmp_path)
    report = wf.build_inventory(client)

    assert client.list_wiki_pages() == ["raw/docs/example.md"]
    assert report["page_count"] == 1
    assert report["source_count"] == 1
    assert report["pages"][0]["path"] == "40-wiki/raw/docs/example.md"
    assert report["sources"][0]["url"] == "https://example.com/current"


def test_local_client_rejects_wiki_path_traversal(tmp_path):
    (tmp_path / "40-wiki").mkdir()
    (tmp_path / "secret.md").write_text("outside", encoding="utf-8")
    client = wf.LocalVaultClient(tmp_path)

    with pytest.raises(ValueError, match="relative path"):
        client.read_wiki_page("../../secret")


def test_local_client_rejects_raw_path_traversal(tmp_path):
    (tmp_path / "40-wiki").mkdir()
    (tmp_path / "secret.md").write_text("outside", encoding="utf-8")
    client = wf.LocalVaultClient(tmp_path)

    with pytest.raises(ValueError, match="relative path"):
        client.read_raw_file("../../secret.md")


def test_local_client_rejects_symlink_escape(tmp_path):
    wiki = tmp_path / "40-wiki"
    wiki.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (wiki / "linked.md").symlink_to(outside)
    client = wf.LocalVaultClient(tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        client.read_wiki_page("linked.md")
    assert client.list_wiki_pages() == []


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
