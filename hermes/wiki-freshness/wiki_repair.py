#!/usr/bin/env python3
"""Deterministic, backup-first structural repair for the AnITGuru 40-wiki tree.

This tool fixes only issues that can be resolved from the wiki's own schema and
frontmatter. It never guesses an ambiguous topic classification and never
replaces an existing destination file.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TYPE_TO_FOLDER = {
    "entity": "entities",
    "concept": "concepts",
    "service": "services",
    "infrastructure": "infrastructure",
    "standard": "standards",
    "decision": "decisions",
    "runbook": "runbooks",
    "comparison": "comparisons",
    "query": "queries",
    # SCHEMA.md permits summaries but has no summaries folder. Reusable
    # summaries belong with saved queries unless the schema gains a folder.
    "summary": "queries",
}
FOLDER_TO_TYPE = {
    "entities": "entity",
    "concepts": "concept",
    "services": "service",
    "infrastructure": "infrastructure",
    "standards": "standard",
    "decisions": "decision",
    "runbooks": "runbook",
    "comparisons": "comparison",
    "queries": "query",
}
FOLDER_TO_HEADING = {
    "entities": "Entities",
    "concepts": "Concepts",
    "services": "Services",
    "infrastructure": "Infrastructure",
    "standards": "Standards",
    "decisions": "Decisions",
    "runbooks": "Runbooks",
    "comparisons": "Comparisons",
    "queries": "Queries",
}
SKIP_FILES = {"SCHEMA.md", "index.md", "log.md", "freshness-report.md"}
REQUIRED_DEFAULTS = {
    "tags": "[]",
    "sources": "[]",
    "confidence": "medium",
    "contested": "false",
}


def _frontmatter_match(text: str) -> re.Match[str] | None:
    return re.match(r"^---\s*\n(.*?)\n---(?:\n|$)", text, re.DOTALL)


def frontmatter_value(text: str, key: str) -> str | None:
    match = _frontmatter_match(text)
    if not match:
        return None
    found = re.search(rf"^{re.escape(key)}\s*:\s*(.*?)\s*$", match.group(1), re.MULTILINE)
    if not found:
        return None
    raw = found.group(1).strip()
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return str(json.loads(raw))
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _title_from_text(path: Path, text: str) -> str:
    title = frontmatter_value(text, "title")
    if title:
        return title
    heading = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return path.stem.replace("-", " ").title()


def _slugify(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "untitled"


def _body_without_frontmatter(text: str) -> str:
    match = _frontmatter_match(text)
    return text[match.end():] if match else text


def _summary_from_text(text: str) -> str:
    body = _body_without_frontmatter(text)
    paragraphs: list[str] = []
    current: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if line.lower().startswith(("status:", "last updated:")):
            continue
        if line.startswith(("#", "```", "|", ">", "- ", "* ")):
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    summary = paragraphs[0] if paragraphs else "Maintained wiki page."
    summary = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), summary)
    summary = summary.replace("**", "").replace("`", "")
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:197] + "..." if len(summary) > 200 else summary


def _is_import_capture(text: str) -> bool:
    if frontmatter_value(text, "type"):
        return False
    return bool(
        frontmatter_value(text, "source")
        and frontmatter_value(text, "fetched_at")
        and frontmatter_value(text, "status")
    )


def _set_frontmatter_value(lines: list[str], key: str, value: str) -> None:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}: {value}"
            return
    lines.append(f"{key}: {value}")


def _yaml_string(value: str) -> str:
    """Encode a string as a JSON-quoted scalar, which is valid YAML."""
    return json.dumps(value, ensure_ascii=False)


def _has_symlink_component(path: Path, root: Path) -> bool:
    """Return True when path or any component below root is a symlink."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _ensure_frontmatter(path: Path, text: str, inferred_type: str, today: date) -> str:
    match = _frontmatter_match(text)
    title = _title_from_text(path, text)
    today_text = today.isoformat()
    old_type = frontmatter_value(text, "type")

    if match:
        lines = match.group(1).splitlines()
        body = text[match.end():]
    else:
        lines = []
        body = text

    changed = match is None
    if frontmatter_value(text, "title") is None:
        _set_frontmatter_value(lines, "title", _yaml_string(title))
        changed = True
    if frontmatter_value(text, "created") is None:
        _set_frontmatter_value(lines, "created", today_text)
        changed = True
    if frontmatter_value(text, "updated") is None:
        _set_frontmatter_value(lines, "updated", today_text)
        changed = True

    if old_type != inferred_type:
        if old_type and old_type not in TYPE_TO_FOLDER:
            _set_frontmatter_value(lines, "legacy_type", _yaml_string(old_type))
        _set_frontmatter_value(lines, "type", inferred_type)
        changed = True

    for key, default in REQUIRED_DEFAULTS.items():
        if frontmatter_value(text, key) is None:
            _set_frontmatter_value(lines, key, default)
            changed = True

    if not changed:
        return text
    _set_frontmatter_value(lines, "updated", today_text)
    return "---\n" + "\n".join(lines) + "\n---\n" + body.lstrip("\n")


def _ensure_required_frontmatter(path: Path, text: str, page_type: str, today: date) -> str:
    """Fill required schema keys without changing a valid explicit type."""
    return _ensure_frontmatter(path, text, page_type, today)


def _add_index_entry(index_text: str, heading: str, entry: str) -> str:
    marker = f"## {heading}"
    start = index_text.find(marker)
    if start < 0:
        return index_text.rstrip() + f"\n\n{marker}\n\n{entry}\n"
    next_heading = index_text.find("\n## ", start + len(marker))
    end = len(index_text) if next_heading < 0 else next_heading
    section = index_text[start:end].rstrip()
    replacement = section + "\n\n" + entry + "\n"
    if next_heading < 0:
        return index_text[:start] + replacement
    return index_text[:start] + replacement + "\n" + index_text[end:].lstrip("\n")


def _update_index_header(index_text: str, today: date, total: int) -> str:
    replacement = f"> Last updated: {today.isoformat()} | Total curated pages: {total}"
    pattern = r"^> Last updated: .*?\| Total curated pages: \d+[^\S\r\n]*$"
    if re.search(pattern, index_text, re.MULTILINE):
        return re.sub(pattern, replacement, index_text, count=1, flags=re.MULTILINE)
    lines = index_text.splitlines()
    insert_at = 1 if lines else 0
    lines[insert_at:insert_at] = ["", replacement]
    return "\n".join(lines) + ("\n" if index_text.endswith("\n") else "")


class BackupSession:
    def __init__(self, vault_root: Path, backup_root: Path | None):
        self.vault_root = vault_root
        root = backup_root or (Path.home() / ".hermes/backups/wiki-freshness")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = root / stamp
        self._seen: set[Path] = set()

    def copy(self, path: Path) -> None:
        if path in self._seen or not path.exists():
            return
        if _has_symlink_component(path, self.vault_root):
            raise RuntimeError(f"refusing to back up through a symlink: {path}")
        resolved = path.resolve()
        if resolved != self.vault_root and self.vault_root not in resolved.parents:
            raise RuntimeError(f"backup source escapes vault: {path}")
        rel = path.relative_to(self.vault_root)
        target = self.path / "vault" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        self._seen.add(path)

    def write_manifest(self, result: dict[str, Any]) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "vault": str(self.vault_root),
            "applied": result["applied"],
            "blocked": result["blocked"],
        }
        (self.path / "manifest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def repair_vault(
    vault_root: Path,
    *,
    apply: bool = False,
    backup_root: Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    vault_root = Path(vault_root).resolve()
    wiki = vault_root / "40-wiki"
    if not wiki.is_dir():
        raise FileNotFoundError(f"40-wiki directory not found under {vault_root}")
    if wiki.is_symlink() or wiki.resolve().parent != vault_root:
        raise RuntimeError(f"refusing symlinked or escaped 40-wiki root: {wiki}")
    today = today or date.today()

    planned: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    backup = BackupSession(vault_root, backup_root) if apply else None

    # These are shared mutation targets. Reject symlinks before touching any
    # page so a crafted index/log cannot turn a later write into an escape.
    for protected in (wiki / "index.md", wiki / "log.md"):
        if _has_symlink_component(protected, wiki):
            raise RuntimeError(f"refusing symlinked wiki control file: {protected}")

    for source in sorted(wiki.rglob("*.md")):
        rel = source.relative_to(wiki)
        if source.name in SKIP_FILES or rel.parts[0] == "raw":
            continue
        if _has_symlink_component(source, wiki):
            blocked.append({"kind": "symlink", "path": rel.as_posix()})
            continue
        text = source.read_text(encoding="utf-8", errors="replace")

        if _is_import_capture(text):
            destination = wiki / "raw/docs/imported-web-docs" / f"{_slugify(source.stem)}.md"
            action = {
                "kind": "move_import",
                "path": rel.as_posix(),
                "to": destination.relative_to(wiki).as_posix(),
            }
            planned.append(action)
            if _has_symlink_component(destination, wiki):
                blocked.append({
                    "kind": "symlink_destination",
                    "path": rel.as_posix(),
                    "to": destination.relative_to(wiki).as_posix(),
                })
            elif destination.exists():
                blocked.append({
                    "kind": "collision",
                    "path": rel.as_posix(),
                    "to": destination.relative_to(wiki).as_posix(),
                })
            elif apply:
                assert backup is not None
                backup.copy(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                applied.append(action)
            continue

        current_folder = rel.parts[0] if len(rel.parts) > 1 else ""
        current_type = frontmatter_value(text, "type")
        valid_type = current_type if current_type in TYPE_TO_FOLDER else None
        inferred_type = valid_type or FOLDER_TO_TYPE.get(current_folder)
        if not inferred_type:
            blocked.append({
                "kind": "unknown_type",
                "path": rel.as_posix(),
                "type": current_type,
            })
            continue

        expected_folder = TYPE_TO_FOLDER[inferred_type]
        filename = f"{_slugify(source.stem)}.md"
        destination = wiki / expected_folder / filename
        if destination != source and _has_symlink_component(destination, wiki):
            blocked.append({
                "kind": "symlink_destination",
                "path": rel.as_posix(),
                "to": destination.relative_to(wiki).as_posix(),
            })
            continue

        repaired_text = _ensure_required_frontmatter(source, text, inferred_type, today)
        if repaired_text != text:
            action = {"kind": "frontmatter", "path": rel.as_posix(), "type": inferred_type}
            planned.append(action)
            if apply:
                assert backup is not None
                backup.copy(source)
                source.write_text(repaired_text, encoding="utf-8")
                applied.append(action)
                text = repaired_text

        final_path = source
        move_action: dict[str, Any] | None = None
        if destination != source:
            move_action = {
                "kind": "move",
                "path": rel.as_posix(),
                "to": destination.relative_to(wiki).as_posix(),
                "type": inferred_type,
            }
            planned.append(move_action)
            if destination.exists():
                blocked.append({
                    "kind": "collision",
                    "path": rel.as_posix(),
                    "to": destination.relative_to(wiki).as_posix(),
                })
            elif apply:
                assert backup is not None
                backup.copy(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                final_path = destination
                applied.append(move_action)
            elif not apply:
                final_path = destination

        records.append({
            "path": final_path.relative_to(wiki).as_posix(),
            "type": inferred_type,
            "title": _title_from_text(final_path, text),
            "summary": _summary_from_text(text),
            "stem": final_path.stem,
        })

    index_path = wiki / "index.md"
    index_text = index_path.read_text(encoding="utf-8", errors="replace") if index_path.exists() else "# Wiki Index\n"
    updated_index = index_text
    for record in sorted(records, key=lambda item: (TYPE_TO_FOLDER[item["type"]], item["stem"])):
        stem = record["stem"]
        if re.search(r"\[\[" + re.escape(stem) + r"(?:\||\]\])", updated_index):
            continue
        folder = TYPE_TO_FOLDER[record["type"]]
        heading = FOLDER_TO_HEADING[folder]
        entry = f"- [[{stem}]] — {record['summary']}"
        updated_index = _add_index_entry(updated_index, heading, entry)
        planned.append({"kind": "index_add", "path": record["path"], "heading": heading})

    updated_index = _update_index_header(updated_index, today, len(records))
    if updated_index != index_text:
        if not any(action["kind"] == "index_add" for action in planned):
            planned.append({"kind": "index_header", "path": "index.md"})
        if apply:
            assert backup is not None
            backup.copy(index_path)
            index_path.write_text(updated_index, encoding="utf-8")
            for action in [a for a in planned if a["kind"] in {"index_add", "index_header"}]:
                applied.append(action)

    if apply and (applied or blocked):
        assert backup is not None
        log_path = wiki / "log.md"
        backup.copy(log_path)
        lines = [f"\n## Wiki auto-repair — {today.isoformat()}\n"]
        for action in applied:
            kind = action["kind"]
            if kind == "frontmatter":
                lines.append(f"- Auto-repaired frontmatter for `{action['path']}`.\n")
            elif kind in {"move", "move_import"}:
                lines.append(f"- Moved `{action['path']}` to `{action['to']}`.\n")
            elif kind == "index_add":
                lines.append(f"- Added `{action['path']}` to `index.md`.\n")
            elif kind == "index_header":
                lines.append("- Refreshed `index.md` date/count metadata.\n")
        if blocked:
            for item in blocked:
                lines.append(f"- BLOCKED `{item['path']}` ({item['kind']}); no destructive action taken.\n")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.writelines(lines)

    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "vault": str(vault_root),
        "planned": planned,
        "applied": applied,
        "blocked": blocked,
        "planned_count": len(planned),
        "applied_count": len(applied),
        "blocked_count": len(blocked),
        "curated_pages": len(records),
    }
    if apply and (applied or blocked):
        assert backup is not None
        backup.write_manifest(result)
        result["backup"] = str(backup.path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup-first deterministic 40-wiki structural repair")
    parser.add_argument("--vault", default=None, help="Vault root containing 40-wiki/")
    parser.add_argument("--apply", action="store_true", help="Apply safe repairs; default is dry-run")
    parser.add_argument("--backup-root", default=None, help="External root for timestamped backups")
    args = parser.parse_args()

    vault = Path(args.vault or Path.home() / "02-Areas/Personal")
    result = repair_vault(
        vault,
        apply=args.apply,
        backup_root=Path(args.backup_root).expanduser() if args.backup_root else None,
    )
    print(f"[wiki-repair] {result['mode'].upper()} — curated={result['curated_pages']} planned={result['planned_count']} applied={result['applied_count']} blocked={result['blocked_count']}")
    for action in result["planned"]:
        suffix = f" -> {action['to']}" if "to" in action else ""
        print(f"  {action['kind']}: {action['path']}{suffix}")
    for item in result["blocked"]:
        suffix = f" -> {item['to']}" if "to" in item else ""
        print(f"  BLOCKED {item['kind']}: {item['path']}{suffix}")
    if result.get("backup"):
        print(f"  backup: {result['backup']}")


if __name__ == "__main__":
    main()
