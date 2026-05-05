#!/usr/bin/env python3
"""Daily user-file organizer for Ace.

Scope is intentionally narrow: root-level files only in configured user folders.
Never touches system locations, hidden files, subfolder contents, git repos, or fresh files.
Writes JSONL manifest and Markdown report for audit/rollback.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/Users/sva/File Inbox/file-organization.json")
USER_HOME = Path("/Users/sva").resolve()
TRASH = USER_HOME / ".Trash"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def collision_safe(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def file_ext(path: Path) -> str:
    if path.is_dir() and path.suffix.lower() == ".app":
        return "app"
    return path.suffix.lower().lstrip(".")


def fresh(path: Path, min_age_minutes: int) -> bool:
    age_seconds = dt.datetime.now().timestamp() - path.stat().st_mtime
    return age_seconds < min_age_minutes * 60


def should_skip(path: Path, cfg: dict[str, Any], root_cfg: dict[str, Any] | None = None) -> tuple[bool, str]:
    name = path.name
    if name in set(cfg.get("never_touch_names", [])):
        return True, "never-touch-name"
    if name.startswith("."):
        return True, "hidden-dotfile"
    resolved = path.resolve()
    if not is_under(resolved, USER_HOME):
        return True, "outside-user-home"
    for p in cfg.get("never_touch_paths", []):
        never = Path(p).expanduser()
        if resolved == never.resolve() or is_under(resolved, never):
            return True, f"never-touch-path:{never}"
    if path.is_dir():
        if (path / ".git").exists():
            return True, "git-repo"
        # Root-level directories are only moved for roots that explicitly request it
        # (Desktop: yes; Documents/Pictures/Movies/Downloads: no by default).
        if file_ext(path) != "app" and not (root_cfg or {}).get("move_directories", False):
            return True, "directory"
    return False, ""


def match_rule(path: Path, root: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    ext = file_ext(path)
    name = path.name
    for rule in cfg.get("rules", []):
        only_under = rule.get("only_under")
        if only_under and not is_under(path, Path(only_under)):
            continue
        exts = set(e.lower().lstrip(".") for e in rule.get("extensions", []))
        prefixes = tuple(rule.get("filename_prefixes", []))
        ext_ok = not exts or ext in exts
        prefix_ok = not prefixes or name.startswith(prefixes)
        if ext_ok and prefix_ok:
            return rule
    return None


def classify(path: Path, root_cfg: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, Path | None, str]:
    rule = match_rule(path, Path(root_cfg["path"]), cfg)
    if rule:
        if rule.get("action") == "trash":
            return "trash", TRASH / path.name, rule["name"]
        return "move", Path(rule["destination"]) / path.name, rule["name"]
    if root_cfg.get("clean_root"):
        return "move", Path(root_cfg["fallback"]) / path.name, "fallback-clean-root"
    return "report", None, "unmatched"


def iter_candidates(root_cfg: dict[str, Any]):
    root = Path(root_cfg["path"]).expanduser()
    if not root.exists():
        return
    for item in root.iterdir():
        yield item


def apply_action(src: Path, dst: Path, dry_run: bool) -> Path:
    dst = collision_safe(dst)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--dry-run", action="store_true", help="Report only; overrides config mode")
    ap.add_argument("--apply", action="store_true", help="Apply; overrides config mode")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    mode = cfg.get("mode", "dry-run")
    if args.dry_run:
        mode = "dry-run"
    if args.apply:
        mode = "apply"
    dry_run = mode != "apply"

    stamp = now_stamp()
    manifest_dir = Path(cfg["manifest_dir"])
    report_dir = Path(cfg["report_dir"])
    manifest_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{stamp}.jsonl"
    report_path = report_dir / f"{stamp}.md"

    counts = {"scanned": 0, "ignored": 0, "moved": 0, "trashed": 0, "reported": 0, "errors": 0}
    rows: list[dict[str, Any]] = []
    min_age = int(cfg.get("min_age_minutes", 60))

    for root_cfg in cfg.get("allow_roots", []):
        for path in iter_candidates(root_cfg) or []:
            counts["scanned"] += 1
            rec: dict[str, Any] = {"source": str(path), "root": root_cfg["path"], "time": stamp}
            try:
                skip, reason = should_skip(path, cfg, root_cfg)
                if skip:
                    counts["ignored"] += 1
                    rec.update({"action": "ignore", "reason": reason})
                    rows.append(rec)
                    continue
                if fresh(path, min_age):
                    counts["ignored"] += 1
                    rec.update({"action": "ignore", "reason": f"fresh-under-{min_age}m"})
                    rows.append(rec)
                    continue

                action, dest, reason = classify(path, root_cfg, cfg)
                rec.update({
                    "action": action,
                    "reason": reason,
                    "size": path.stat().st_size if path.is_file() else None,
                    "mtime": path.stat().st_mtime,
                    "sha256": sha256(path) if path.is_file() else None,
                })
                if action == "move" and dest:
                    final = apply_action(path, dest, dry_run)
                    counts["moved"] += 1
                    rec.update({"destination": str(final), "dry_run": dry_run})
                elif action == "trash" and dest:
                    final = apply_action(path, dest, dry_run)
                    counts["trashed"] += 1
                    rec.update({"destination": str(final), "dry_run": dry_run})
                else:
                    counts["reported"] += 1
                    rec.update({"dry_run": dry_run})
                rows.append(rec)
            except Exception as e:
                counts["errors"] += 1
                rec.update({"action": "error", "error": repr(e)})
                rows.append(rec)

    with manifest_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")

    report_lines = [
        f"# User file organization report — {stamp}",
        "",
        f"Mode: `{mode}`",
        "",
        "## Counts",
        "",
    ]
    for k, v in counts.items():
        report_lines.append(f"- {k}: {v}")
    report_lines += ["", "## Actions", ""]
    for row in rows:
        if row.get("action") in {"move", "trash", "report", "error"}:
            report_lines.append(f"- {row.get('action')} `{row.get('source')}` → `{row.get('destination', '')}` ({row.get('reason', row.get('error', ''))})")
    report_lines += ["", f"Manifest: `{manifest_path}`", ""]
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    summary = {"mode": mode, "counts": counts, "manifest": str(manifest_path), "report": str(report_path)}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
