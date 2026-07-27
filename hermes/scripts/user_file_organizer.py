#!/usr/bin/env python3
"""Bounded PARA-aware root-level file maintenance for SVA's Mac.

A local model may write proposals, but this script alone owns mutations. Every
proposal is revalidated against source fingerprints, confidence, filename, and
destination allowlists before use. Ambiguous files follow deterministic rules
into 03-Resources/File Intake. Nothing is permanently deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parents[1] / "file-organizer" / "file-organization.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {"user_home", "manifest_dir", "report_dir", "allow_roots", "rules", "para"}
    missing = sorted(required - set(cfg))
    if missing:
        raise ValueError(f"missing config keys: {', '.join(missing)}")
    return cfg


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def collision_safe(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    index = 1
    while True:
        candidate = dest.parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def file_ext(path: Path) -> str:
    if path.is_dir() and path.suffix.lower() == ".app":
        return "app"
    return path.suffix.lower().lstrip(".")


def fresh(path: Path, min_age_minutes: int) -> bool:
    age_seconds = dt.datetime.now().timestamp() - path.stat().st_mtime
    return age_seconds < min_age_minutes * 60


def user_home(cfg: dict[str, Any]) -> Path:
    return Path(cfg["user_home"]).expanduser().resolve()


def trash_root(cfg: dict[str, Any]) -> Path:
    return user_home(cfg) / ".Trash"


def allowed_source_roots(cfg: dict[str, Any]) -> list[Path]:
    return [Path(root["path"]).expanduser().resolve() for root in cfg.get("allow_roots", [])]


def allowed_destination_roots(cfg: dict[str, Any]) -> list[Path]:
    para = cfg.get("para", {})
    roots = [Path(path).expanduser().resolve() for path in para.get("resource_destinations", {}).values()]
    for item in para.get("allowed_projects", {}).values():
        roots.append(Path(item["path"]).expanduser().resolve())
    for item in para.get("allowed_areas", {}).values():
        path = item["path"] if isinstance(item, dict) else item
        roots.append(Path(path).expanduser().resolve())
    roots.append(trash_root(cfg).resolve())
    return roots


def source_is_allowed(path: Path, cfg: dict[str, Any]) -> bool:
    resolved = path.resolve()
    return any(is_under(resolved, root) for root in allowed_source_roots(cfg))


def destination_is_allowed(path: Path, cfg: dict[str, Any]) -> bool:
    resolved_parent = path.parent.resolve()
    return any(resolved_parent == root or is_under(resolved_parent, root) for root in allowed_destination_roots(cfg))


def should_skip(
    path: Path, cfg: dict[str, Any], root_cfg: dict[str, Any] | None = None
) -> tuple[bool, str]:
    name = path.name
    if name in set(cfg.get("never_touch_names", [])):
        return True, "never-touch-name"
    if name.startswith("."):
        return True, "hidden-dotfile"
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return True, "unresolvable-source"
    if not is_under(resolved, user_home(cfg)):
        return True, "outside-user-home"
    if not source_is_allowed(resolved, cfg):
        return True, "outside-allowed-source-roots"
    for raw in cfg.get("never_touch_paths", []):
        protected = Path(raw).expanduser()
        try:
            protected_resolved = protected.resolve()
        except OSError:
            protected_resolved = protected.absolute()
        if resolved == protected_resolved or is_under(resolved, protected_resolved):
            return True, f"never-touch-path:{protected}"
    if path.is_symlink():
        return True, "symlink"
    if path.is_dir():
        if (path / ".git").exists():
            return True, "git-repo"
        if file_ext(path) != "app" and not (root_cfg or {}).get("move_directories", False):
            return True, "directory"
    return False, ""


def rule_applies_to_root(rule: dict[str, Any], path: Path) -> bool:
    roots = [Path(raw).expanduser().resolve() for raw in rule.get("roots", [])]
    return not roots or any(is_under(path.resolve(), root) for root in roots)


def match_rule(path: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    ext = file_ext(path)
    name = path.name
    for rule in cfg.get("rules", []):
        if not rule_applies_to_root(rule, path):
            continue
        kinds = set(rule.get("kinds", []))
        kind = "directory" if path.is_dir() else "file"
        if kinds and kind not in kinds:
            continue
        extensions = {item.lower().lstrip(".") for item in rule.get("extensions", [])}
        prefixes = tuple(rule.get("filename_prefixes", []))
        patterns = tuple(rule.get("filename_patterns", []))
        ext_ok = not extensions or ext in extensions
        prefix_ok = not prefixes or name.startswith(prefixes)
        pattern_ok = not patterns or any(re.search(pattern, name, re.IGNORECASE) for pattern in patterns)
        if ext_ok and prefix_ok and pattern_ok:
            return rule
    return None


def resource_destination(key: str, cfg: dict[str, Any]) -> Path | None:
    raw = cfg.get("para", {}).get("resource_destinations", {}).get(key)
    return Path(raw).expanduser() if raw else None


def deterministic_classify(
    path: Path, root_cfg: dict[str, Any], cfg: dict[str, Any]
) -> tuple[str, Path | None, str]:
    rule = match_rule(path, cfg)
    if rule:
        if rule.get("action") == "trash":
            return "trash", trash_root(cfg) / path.name, rule["name"]
        key = rule.get("destination_key")
        destination = (
            proposal_destination(str(key), cfg)
            if key and ":" in str(key)
            else resource_destination(str(key), cfg)
        )
        if not key:
            destination = Path(rule["destination"]).expanduser()
        if destination is None:
            return "report", None, f"missing-destination:{key}"
        return "move", destination / path.name, rule["name"]
    if path.is_dir():
        return "report", None, "unmatched-directory"
    if root_cfg.get("clean_root"):
        key = root_cfg.get("fallback_key")
        destination = resource_destination(key, cfg) if key else None
        if destination:
            return "move", destination / path.name, "fallback-clean-root"
    return "report", None, "unmatched"


def sanitize_suggested_name(raw: str, original: Path) -> str | None:
    raw = Path(str(raw)).name.strip()
    if not raw or raw in {".", ".."} or raw.startswith("."):
        return None
    original_suffix = original.suffix.lower()
    supplied_suffix = Path(raw).suffix.lower()
    stem = Path(raw).stem if supplied_suffix else raw
    stem = stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    stem = re.sub(r"-{2,}", "-", stem)
    if len(stem) < 4 or len(stem) > 100:
        return None
    suffix = original_suffix or supplied_suffix
    if supplied_suffix and original_suffix and supplied_suffix != original_suffix:
        return None
    return f"{stem}{suffix}"


def needs_local_name(path: Path, cfg: dict[str, Any]) -> bool:
    naming = cfg.get("local_naming", {})
    extensions = {str(item).lower().lstrip(".") for item in naming.get("extensions", [])}
    patterns = naming.get("generic_name_patterns", [])
    return file_ext(path) in extensions and any(
        re.search(str(pattern), path.stem, re.IGNORECASE) for pattern in patterns
    )


def proposal_destination(key: str, cfg: dict[str, Any]) -> Path | None:
    if key.startswith("resource:"):
        return resource_destination(key.split(":", 1)[1], cfg)
    if key.startswith("project:"):
        project_key = key.split(":", 1)[1]
        project = cfg.get("para", {}).get("allowed_projects", {}).get(project_key)
        if not project:
            return None
        root = Path(project["path"]).expanduser()
        return root / project.get("incoming_subdir", "Incoming")
    if key.startswith("area:"):
        area_key = key.split(":", 1)[1]
        area = cfg.get("para", {}).get("allowed_areas", {}).get(area_key)
        if not area:
            return None
        if isinstance(area, dict):
            return Path(area["path"]).expanduser() / area.get("incoming_subdir", "Incoming")
        return Path(area).expanduser() / "Incoming"
    return None


def proposal_confidence_threshold(key: str, cfg: dict[str, Any]) -> float:
    kind = key.split(":", 1)[0]
    thresholds = cfg.get("proposal_confidence_thresholds", {})
    return float(thresholds.get(kind, cfg.get("proposal_confidence_threshold", 0.92)))


def validated_proposal_name(
    path: Path,
    proposal: dict[str, Any],
    min_name_confidence: float = 0.0,
) -> str | None:
    try:
        stat = path.stat()
        if int(proposal.get("size", -1)) != stat.st_size:
            return None
        if abs(float(proposal.get("mtime", -1)) - stat.st_mtime) > 0.001:
            return None
        if path.is_file() and proposal.get("sha256") != sha256(path):
            return None
        name_confidence = float(proposal.get("name_confidence", proposal.get("confidence", 0)))
        if name_confidence < min_name_confidence:
            return None
        return sanitize_suggested_name(str(proposal.get("suggested_name", "")), path)
    except (OSError, TypeError, ValueError):
        return None


def validate_proposal(path: Path, proposal: dict[str, Any], cfg: dict[str, Any]) -> Path | None:
    try:
        name = validated_proposal_name(path, proposal)
        if not name:
            return None
        key = str(proposal.get("destination_key", ""))
        naming = cfg.get("local_naming", {})
        name_confidence = float(proposal.get("name_confidence", proposal.get("confidence", 0)))
        destination_confidence = float(
            proposal.get("destination_confidence", proposal.get("confidence", 0))
        )
        if key == "resource:review":
            if not bool(naming.get("auto_apply_review", False)):
                return None
            if name_confidence < float(naming.get("review_name_confidence_threshold", 0.90)):
                return None
            if destination_confidence < float(
                naming.get("review_destination_confidence_threshold", 0.75)
            ):
                return None
        else:
            destination_threshold = proposal_confidence_threshold(key, cfg)
            name_threshold = float(
                naming.get("proposal_name_confidence_threshold", 0.90)
            )
            if (
                name_confidence < name_threshold
                or destination_confidence < destination_threshold
            ):
                return None
        base = proposal_destination(key, cfg)
        if not name or base is None:
            return None
        destination = base / name
        if not destination_is_allowed(destination, cfg):
            return None
        return destination
    except (OSError, TypeError, ValueError):
        return None


def load_latest_proposals(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    proposal_dir = Path(cfg.get("proposal_dir", "")).expanduser()
    if not proposal_dir.exists():
        return {}
    files = sorted(proposal_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return {}
    max_age = float(cfg.get("proposal_max_age_hours", 24)) * 3600
    proposals: dict[str, dict[str, Any]] = {}
    now = dt.datetime.now().timestamp()
    for proposal_file in files:
        if now - proposal_file.stat().st_mtime > max_age:
            continue
        for line in proposal_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            source = row.get("source")
            if source:
                proposals.setdefault(str(Path(source).expanduser()), row)
    return proposals


def iter_candidates(root_cfg: dict[str, Any]):
    root = Path(root_cfg["path"]).expanduser()
    if not root.exists() or not root.is_dir():
        return
    for item in root.iterdir():
        if root_cfg.get("loose_files_only") and not item.is_file():
            continue
        yield item


def apply_action(
    src: Path,
    dst: Path,
    dry_run: bool,
    cfg: dict[str, Any],
    allow_in_place: bool = False,
) -> Path:
    if not source_is_allowed(src, cfg):
        raise ValueError(f"source escaped allowlist: {src}")
    if allow_in_place:
        if src.parent.resolve() != dst.parent.resolve() or not source_is_allowed(dst, cfg):
            raise ValueError(f"in-place rename escaped source root: {dst}")
    elif not destination_is_allowed(dst, cfg):
        raise ValueError(f"destination escaped allowlist: {dst}")
    final = collision_safe(dst)
    if not dry_run:
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(final))
    return final


def write_artifacts(
    stamp: str,
    mode: str,
    counts: dict[str, int],
    rows: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> tuple[Path, Path]:
    manifest_dir = Path(cfg["manifest_dir"]).expanduser()
    report_dir = Path(cfg["report_dir"]).expanduser()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{stamp}.jsonl"
    report_path = report_dir / f"{stamp}.md"
    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    lines = [f"# PARA file maintenance — {stamp}", "", f"Mode: `{mode}`", "", "## Counts", ""]
    lines.extend(f"- {key}: {value}" for key, value in counts.items())
    lines.extend(["", "## Actions", ""])
    for row in rows:
        if row.get("action") in {"move", "rename", "trash", "report", "blocked", "error"}:
            lines.append(
                f"- {row.get('action')} `{row.get('source')}` → "
                f"`{row.get('destination', '')}` ({row.get('reason', row.get('error', ''))})"
            )
    lines.extend(["", f"Manifest: `{manifest_path}`", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return manifest_path, report_path


def run(
    config_path: Path = CONFIG_PATH,
    mode: str | None = None,
    rename_root: Path | None = None,
) -> int:
    cfg = load_config(config_path)
    if rename_root is not None:
        root = rename_root.expanduser().resolve()
        cfg["allow_roots"] = [
            {
                "path": str(root),
                "clean_root": False,
                "move_directories": False,
                "rename_in_place_only": True,
            }
        ]
    selected_mode = mode or cfg.get("mode", "dry-run")
    dry_run = selected_mode != "apply"
    stamp = now_stamp()
    counts = {
        "scanned": 0,
        "ignored": 0,
        "planned": 0,
        "moved": 0,
        "renamed": 0,
        "trashed": 0,
        "reported": 0,
        "blocked": 0,
        "proposal_used": 0,
        "errors": 0,
    }
    rows: list[dict[str, Any]] = []
    proposals = load_latest_proposals(cfg)
    min_age = int(cfg.get("min_age_minutes", 60))
    max_actions = int(cfg.get("max_auto_actions", 40))
    action_count = 0

    for root_cfg in cfg.get("allow_roots", []):
        for path in iter_candidates(root_cfg) or []:
            counts["scanned"] += 1
            record: dict[str, Any] = {"source": str(path), "root": root_cfg["path"], "time": stamp}
            try:
                skip, reason = should_skip(path, cfg, root_cfg)
                if skip:
                    counts["ignored"] += 1
                    record.update({"action": "ignore", "reason": reason})
                    rows.append(record)
                    continue
                if fresh(path, min_age):
                    counts["ignored"] += 1
                    record.update({"action": "ignore", "reason": f"fresh-under-{min_age}m"})
                    rows.append(record)
                    continue

                stat = path.stat()
                fingerprint = sha256(path) if path.is_file() else None
                proposal = proposals.get(str(path))
                proposed_name = None
                if root_cfg.get("rename_in_place_only"):
                    threshold = float(
                        cfg.get("local_naming", {}).get("rename_name_confidence_threshold", 0.50)
                    )
                    proposed_name = (
                        validated_proposal_name(path, proposal, threshold) if proposal else None
                    )
                    if proposed_name:
                        action, destination, reason = (
                            "rename",
                            path.with_name(proposed_name),
                            "validated-local-image-name",
                        )
                        counts["proposal_used"] += 1
                    else:
                        action, destination, reason = "report", None, "no-valid-rename-proposal"
                    proposed_destination = None
                else:
                    name_threshold = float(
                        cfg.get("local_naming", {}).get(
                            "proposal_name_confidence_threshold", 0.90
                        )
                    )
                    proposed_name = (
                        validated_proposal_name(path, proposal, name_threshold)
                        if proposal
                        else None
                    )
                    proposed_destination = validate_proposal(path, proposal, cfg) if proposal else None
                    action, destination, reason = deterministic_classify(path, root_cfg, cfg)
                generic_reasons = {
                    "screenshots",
                    "images",
                    "documents",
                    "archives",
                    "media",
                    "code-config-snippets",
                    "fallback-clean-root",
                    "unmatched",
                }
                if (
                    not root_cfg.get("rename_in_place_only")
                    and proposed_destination is not None
                    and action != "trash"
                ):
                    if action == "move" and destination is not None and reason not in generic_reasons:
                        destination = destination.parent / proposed_destination.name
                        reason = f"{reason}+validated-local-name"
                    else:
                        action, destination, reason = (
                            "move",
                            proposed_destination,
                            "validated-local-model-proposal",
                        )
                    counts["proposal_used"] += 1
                elif (
                    not root_cfg.get("rename_in_place_only")
                    and proposed_name is not None
                    and action == "move"
                    and destination is not None
                ):
                    # A conservative/review placement must not override the
                    # deterministic route, but its independently validated
                    # descriptive filename can still improve the move.
                    destination = destination.parent / proposed_name
                    reason = f"{reason}+validated-local-name"
                    counts["proposal_used"] += 1
                elif (
                    not root_cfg.get("rename_in_place_only")
                    and path.is_file()
                    and action == "move"
                    and needs_local_name(path, cfg)
                ):
                    action, destination, reason = (
                        "report",
                        None,
                        "awaiting-local-name-proposal",
                    )

                record.update(
                    {
                        "action": action,
                        "reason": reason,
                        "size": stat.st_size if path.is_file() else None,
                        "mtime": stat.st_mtime,
                        "sha256": fingerprint,
                        "dry_run": dry_run,
                    }
                )
                if action in {"move", "rename", "trash"} and destination is not None:
                    if action_count >= max_actions:
                        counts["blocked"] += 1
                        record.update({"action": "blocked", "reason": f"action-cap-{max_actions}"})
                    else:
                        final = apply_action(
                            path,
                            destination,
                            dry_run,
                            cfg,
                            allow_in_place=action == "rename",
                        )
                        action_count += 1
                        counts["planned"] += 1
                        count_key = {
                            "move": "moved",
                            "rename": "renamed",
                            "trash": "trashed",
                        }[action]
                        counts[count_key] += 1
                        record["destination"] = str(final)
                else:
                    counts["reported"] += 1
                rows.append(record)
            except Exception as exc:  # continue to produce a complete audit manifest
                counts["errors"] += 1
                record.update({"action": "error", "error": repr(exc)})
                rows.append(record)

    manifest_path, report_path = write_artifacts(stamp, selected_mode, counts, rows, cfg)
    summary = {
        "mode": selected_mode,
        "counts": counts,
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if counts["errors"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="plan only")
    modes.add_argument("--apply", action="store_true", help="apply bounded validated actions")
    parser.add_argument(
        "--rename-root",
        type=Path,
        help="rename validated proposal files in place within this immediate-child root",
    )
    args = parser.parse_args()
    mode = "dry-run" if args.dry_run else ("apply" if args.apply else None)
    return run(Path(args.config).expanduser(), mode, args.rename_root)


if __name__ == "__main__":
    raise SystemExit(main())
