from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wiki_repair as wr


SCHEMA = """# Wiki Schema

## Type folders
- `raw/` — immutable source captures.
- `entities/` — people and products.
- `concepts/` — reusable ideas.
- `services/` — durable docs for apps/services.
- `infrastructure/` — hosts and networks.
- `standards/` — SOPs and policies.
- `decisions/` — decisions.
- `runbooks/` — operational procedures.
- `comparisons/` — evaluations.
- `queries/` — reusable answers.
"""

INDEX = """# Wiki Index

> Last updated: 2026-01-01 | Total curated pages: 0

## Entities

## Concepts

## Services

## Infrastructure

## Standards

## Decisions

## Runbooks

## Comparisons

## Queries
"""


def make_vault(tmp_path: Path) -> Path:
    wiki = tmp_path / "40-wiki"
    for name in [
        "raw/docs/imported-web-docs",
        "entities",
        "concepts",
        "services",
        "infrastructure",
        "standards",
        "decisions",
        "runbooks",
        "comparisons",
        "queries",
    ]:
        (wiki / name).mkdir(parents=True, exist_ok=True)
    (wiki / "SCHEMA.md").write_text(SCHEMA, encoding="utf-8")
    (wiki / "index.md").write_text(INDEX, encoding="utf-8")
    (wiki / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
    return tmp_path


def test_dry_run_reports_but_does_not_mutate_missing_frontmatter(tmp_path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/example-runbook.md"
    original = "# Example Runbook\n\nRecover the example service safely.\n"
    page.write_text(original, encoding="utf-8")

    result = wr.repair_vault(vault, apply=False, today=date(2026, 7, 20))

    assert page.read_text(encoding="utf-8") == original
    assert any(a["kind"] == "frontmatter" and a["path"] == "runbooks/example-runbook.md" for a in result["planned"])
    assert any(a["kind"] == "index_add" and a["path"] == "runbooks/example-runbook.md" for a in result["planned"])


def test_apply_repairs_frontmatter_index_log_and_creates_backup(tmp_path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/example-runbook.md"
    page.write_text("# Example Runbook\n\nRecover the example service safely.\n", encoding="utf-8")
    backup_root = tmp_path / "backups"

    result = wr.repair_vault(
        vault,
        apply=True,
        backup_root=backup_root,
        today=date(2026, 7, 20),
    )

    repaired = page.read_text(encoding="utf-8")
    assert "type: runbook" in repaired
    assert wr.frontmatter_value(repaired, "title") == "Example Runbook"
    assert "confidence: medium" in repaired
    index = (vault / "40-wiki/index.md").read_text(encoding="utf-8")
    assert "[[example-runbook]]" in index
    assert "Last updated: 2026-07-20 | Total curated pages: 1\n\n## Entities" in index
    assert "[[example-runbook]] — Recover the example service safely.\n\n## Comparisons" in index
    log = (vault / "40-wiki/log.md").read_text(encoding="utf-8")
    assert "Auto-repaired frontmatter for `runbooks/example-runbook.md`" in log
    assert "Added `runbooks/example-runbook.md` to `index.md`" in log
    assert result["applied_count"] >= 2
    assert any(p.name == "example-runbook.md" for p in backup_root.rglob("example-runbook.md"))
    assert any(p.name == "manifest.json" for p in backup_root.rglob("manifest.json"))


def test_repairs_updated_when_it_is_the_only_missing_required_key(tmp_path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/example-runbook.md"
    page.write_text(
        "---\ntitle: Example Runbook\ncreated: 2026-07-01\ntype: runbook\n"
        "tags: [runbook]\nsources: []\nconfidence: high\ncontested: false\n---\n"
        "# Example Runbook\n",
        encoding="utf-8",
    )

    result = wr.repair_vault(
        vault,
        apply=True,
        backup_root=tmp_path / "backups",
        today=date(2026, 7, 20),
    )

    repaired = page.read_text(encoding="utf-8")
    assert "updated: 2026-07-20" in repaired
    assert any(a["kind"] == "frontmatter" for a in result["applied"])


def test_explicit_type_moves_page_to_matching_folder(tmp_path):
    vault = make_vault(tmp_path)
    src = vault / "40-wiki/runbooks/example-service.md"
    src.write_text(
        "---\ntitle: Example Service\ncreated: 2026-07-01\nupdated: 2026-07-01\n"
        "type: service\ntags: [service]\nsources: []\nconfidence: high\ncontested: false\n---\n"
        "# Example Service\n\nA durable service page.\n",
        encoding="utf-8",
    )

    result = wr.repair_vault(vault, apply=True, backup_root=tmp_path / "backups", today=date(2026, 7, 20))

    dst = vault / "40-wiki/services/example-service.md"
    assert not src.exists()
    assert dst.exists()
    assert any(a["kind"] == "move" and a["to"] == "services/example-service.md" for a in result["applied"])


def test_move_collision_fails_safe_without_overwriting(tmp_path):
    vault = make_vault(tmp_path)
    src = vault / "40-wiki/runbooks/example-service.md"
    dst = vault / "40-wiki/services/example-service.md"
    src.write_text("---\ntitle: Source\ntype: service\n---\nsource", encoding="utf-8")
    dst.write_text("---\ntitle: Target\ntype: service\n---\ntarget", encoding="utf-8")

    result = wr.repair_vault(vault, apply=True, backup_root=tmp_path / "backups", today=date(2026, 7, 20))

    assert src.exists()
    assert dst.read_text(encoding="utf-8").endswith("target")
    assert any(b["kind"] == "collision" and b["path"] == "runbooks/example-service.md" for b in result["blocked"])


def test_import_signature_outside_raw_is_moved_to_imported_docs(tmp_path):
    vault = make_vault(tmp_path)
    src = vault / "40-wiki/services/reference-page.md"
    src.write_text(
        "---\nsource: https://example.com/docs\ntitle: Reference Page\n"
        "fetched_at: 2026-07-20T00:00:00+00:00\nstatus: processed\n---\n\nCaptured docs.\n",
        encoding="utf-8",
    )

    result = wr.repair_vault(vault, apply=True, backup_root=tmp_path / "backups", today=date(2026, 7, 20))

    dst = vault / "40-wiki/raw/docs/imported-web-docs/reference-page.md"
    assert not src.exists()
    assert dst.exists()
    assert any(a["kind"] == "move_import" for a in result["applied"])
    assert "[[reference-page]]" not in (vault / "40-wiki/index.md").read_text(encoding="utf-8")


def test_invalid_type_is_normalized_from_unambiguous_current_folder(tmp_path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/retired-workflow.md"
    page.write_text(
        "---\ntitle: Retired Workflow\ntype: tombstone\ntags: [retired]\n---\n# Retired Workflow\n",
        encoding="utf-8",
    )

    wr.repair_vault(vault, apply=True, backup_root=tmp_path / "backups", today=date(2026, 7, 20))

    repaired = page.read_text(encoding="utf-8")
    assert "type: runbook" in repaired
    assert wr.frontmatter_value(repaired, "legacy_type") == "tombstone"


def test_symlinked_source_is_blocked_and_outside_target_is_unchanged(tmp_path: Path):
    vault = make_vault(tmp_path)
    outside = tmp_path / "outside.md"
    original = "# Project #1\n"
    outside.write_text(original, encoding="utf-8")
    link = vault / "40-wiki/runbooks/linked.md"
    link.symlink_to(outside)

    result = wr.repair_vault(vault, apply=True, today=date(2026, 7, 20))

    assert outside.read_text(encoding="utf-8") == original
    assert link.is_symlink()
    assert any(item["kind"] == "symlink" for item in result["blocked"])


def test_symlinked_wiki_root_is_rejected(tmp_path: Path):
    outside = tmp_path / "outside-wiki"
    outside.mkdir()
    (outside / "runbooks").mkdir()
    page = outside / "runbooks/external.md"
    original = "# External\n"
    page.write_text(original, encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "40-wiki").symlink_to(outside, target_is_directory=True)

    try:
        wr.repair_vault(vault, apply=True, today=date(2026, 7, 20))
    except RuntimeError as exc:
        assert "40-wiki root" in str(exc)
    else:
        raise AssertionError("symlinked 40-wiki root was not rejected")
    assert page.read_text(encoding="utf-8") == original


def test_symlinked_destination_directory_is_blocked(tmp_path: Path):
    vault = make_vault(tmp_path)
    outside = tmp_path / "outside-services"
    outside.mkdir()
    services = vault / "40-wiki/services"
    services.rmdir()
    services.symlink_to(outside, target_is_directory=True)
    page = vault / "40-wiki/runbooks/wrong-place.md"
    original = (
        "---\ntitle: Wrong Place\ncreated: 2026-07-01\nupdated: 2026-07-01\n"
        "type: service\ntags: [service]\nsources: []\nconfidence: high\ncontested: false\n---\n"
        "# Wrong Place\n\nA service page.\n"
    )
    page.write_text(original, encoding="utf-8")

    result = wr.repair_vault(vault, apply=True, today=date(2026, 7, 20))

    assert page.read_text(encoding="utf-8") == original
    assert not (outside / "wrong-place.md").exists()
    assert any(item["kind"] == "symlink_destination" for item in result["blocked"])


def test_generated_title_is_yaml_safe(tmp_path: Path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/project-1.md"
    page.write_text("# Project #1\n\nSafe title repair.\n", encoding="utf-8")

    wr.repair_vault(vault, apply=True, today=date(2026, 7, 20))

    repaired = page.read_text(encoding="utf-8")
    assert 'title: "Project #1"' in repaired
    assert wr.frontmatter_value(repaired, "title") == "Project #1"


def test_backup_preserves_original_before_rewrite_and_move(tmp_path: Path):
    vault = make_vault(tmp_path)
    page = vault / "40-wiki/runbooks/misplaced-service.md"
    original = "---\ntitle: Misplaced Service\ntype: service\n---\n# Misplaced Service\n"
    page.write_text(original, encoding="utf-8")
    backup_root = tmp_path / "backups"

    result = wr.repair_vault(
        vault,
        apply=True,
        backup_root=backup_root,
        today=date(2026, 7, 20),
    )

    backup = Path(result["backup"]) / "vault/40-wiki/runbooks/misplaced-service.md"
    assert backup.read_text(encoding="utf-8") == original
    assert (vault / "40-wiki/services/misplaced-service.md").exists()
