#!/usr/bin/env python3
"""Local-Qwen proposal pass for generic root-level image names.

This script never moves, renames, deletes, or writes beside source files. It
submits bounded local-only image requests to Ollama and writes fingerprinted
JSONL proposals for the deterministic organizer to validate later.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import stat as stat_module
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from user_file_organizer import (
    CONFIG_PATH,
    exact_duplicate_plan,
    file_ext,
    fresh,
    iter_candidates,
    load_config,
    load_latest_proposals,
    now_stamp,
    proposal_confidence_threshold,
    proposal_matches_source,
    sha256,
    should_skip,
)

BASE_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "suggested_name": {
            "type": "string",
            "description": "lowercase descriptive kebab-case filename, including the original extension",
        },
        "destination_key": {"type": "string", "enum": []},
        "name_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "destination_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "suggested_name",
        "destination_key",
        "name_confidence",
        "destination_confidence",
        "summary",
        "reason",
    ],
    "additionalProperties": False,
}


def format_schema(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build destination choices from the deterministic allowlist."""
    schema = json.loads(json.dumps(BASE_FORMAT_SCHEMA))
    para = cfg.get("para", {})
    choices = [f"resource:{key}" for key in para.get("resource_destinations", {})]
    choices.extend(f"project:{key}" for key in para.get("allowed_projects", {}))
    choices.extend(f"area:{key}" for key in para.get("allowed_areas", {}))
    schema["properties"]["destination_key"]["enum"] = sorted(set(choices))
    return schema


def is_generic_name(path: Path, patterns: list[str]) -> bool:
    return any(re.search(pattern, path.stem, flags=re.IGNORECASE) for pattern in patterns)


def source_date(path: Path) -> str:
    patterns = [
        r"(20\d{2})[-_](\d{2})[-_](\d{2})",
        r"(20\d{2})-(\d{2})-(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, path.name)
        if match:
            return "-".join(match.groups())
    return dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def make_prompt(path: Path, cfg: dict[str, Any]) -> str:
    project_lines = []
    for key, project in cfg.get("para", {}).get("allowed_projects", {}).items():
        keywords = ", ".join(project.get("keywords", [])) or "no aliases"
        project_lines.append(f"- project:{key}: {keywords}")
    projects = "\n".join(project_lines) or "- none"
    area_lines = []
    for key, area in cfg.get("para", {}).get("allowed_areas", {}).items():
        keywords = ", ".join(area.get("keywords", [])) if isinstance(area, dict) else ""
        area_lines.append(f"- area:{key}: {keywords or 'no aliases'}")
    areas = "\n".join(area_lines) or "- none"
    return f"""You are a conservative local file-intake classifier for SVA's PARA system.
Inspect the attached image and return only the requested JSON object.

Source filename: {path.name}
Source date: {source_date(path)}

Naming rules:
- Use lowercase kebab-case ASCII.
- Keep the original .{file_ext(path)} extension.
- Prefix the name with {source_date(path)} when it is a screenshot, dated diagram, receipt, or event capture.
- Describe the visible subject, app, diagram, person/event, or purpose; never use generic words alone such as screenshot, image, pic, or file.
- Do not invent names, companies, projects, or sensitive facts that are not visible.
- For people, use generic visible descriptors such as woman, man, person, or group; do not infer identity from a face.
- Keep the stem at most 100 characters.

PARA decision rules:
- project means a time-bounded outcome AND must exactly match one of the allowlisted projects below.
- area means an ongoing responsibility and must exactly match an allowlisted area below; it does not require an active task or deadline.
- Choose area:home-lab-assets for clearly visible owned/operated network hardware, access-point labels, or device inventory evidence.
- Choose area:work-meetings for clearly work-related meeting participant panels, recordings, or call evidence; use resource:review when the meeting could be personal.
- A participant panel is clearly work-related when any tile shows an employer, company, customer, security vendor, corporate bot, or notetaker label. In that case you MUST choose area:work-meetings rather than resource:review.
- Choose area:personal-photography-appreciation for personal portraits, selfies, fashion/editorial photography, or aesthetically appreciated photos with no work, project, or home-lab evidence. You MUST use this area for otherwise ambiguous personal photography; do not choose resource:review merely because aesthetic or editorial intent is not explicit.
- Include clearly visible company or product names in the filename when they distinguish the meeting; do not name private individuals from labels alone.
- resource is the safe default for reusable reference material and unmatched screenshots/images.
- project:mission-control is allowed only when the image clearly shows SVA's Mission Control dashboard or its analytics panel.
- If uncertain, choose resource:review and lower destination_confidence.

Allowlisted projects:
{projects}

Allowlisted areas:
{areas}

Score filename and destination separately. A clear descriptive name may have high name_confidence even when PARA placement is uncertain. Keep both calibrated."""


def ollama_classify(path: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], float]:
    local = cfg.get("local_naming", {})
    endpoint = str(local.get("endpoint", "http://127.0.0.1:11434")).rstrip("/")
    model = str(local.get("model", "qwen3.6:35b-a3b"))
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": format_schema(cfg),
        "options": {"temperature": 0, "top_p": 0.8, "num_predict": 300},
        "messages": [
            {
                "role": "user",
                "content": make_prompt(path, cfg),
                "images": [base64.b64encode(path.read_bytes()).decode("ascii")],
            }
        ],
    }
    request = urllib.request.Request(
        f"{endpoint}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        timeout = float(local.get("request_timeout_seconds", 120))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    elapsed = time.monotonic() - started
    content = body.get("message", {}).get("content", "")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid model JSON: {content[:500]!r}") from exc
    required = set(BASE_FORMAT_SCHEMA["required"])
    if not required.issubset(result):
        raise RuntimeError(f"model JSON missing keys: {sorted(required - set(result))}")
    result["model"] = model
    return result, elapsed


def candidates(cfg: dict[str, Any]) -> list[Path]:
    local = cfg.get("local_naming", {})
    extensions = {item.lower().lstrip(".") for item in local.get("extensions", [])}
    patterns = list(local.get("generic_name_patterns", []))
    max_bytes = int(local.get("max_file_bytes", 12 * 1024 * 1024))
    min_age = int(cfg.get("min_age_minutes", 60))
    duplicate_sources = (
        set(exact_duplicate_plan(cfg, min_age))
        if not local.get("rename_in_place_only", False)
        else set()
    )
    recent_proposals = load_latest_proposals(cfg)
    found: list[Path] = []
    for root_cfg in cfg.get("allow_roots", []):
        for path in iter_candidates(root_cfg) or []:
            try:
                # Cheap lexical checks must happen before resolve/stat-heavy policy
                # validation. In particular, never follow root-level symlinks or
                # inspect unrelated directories while looking for generic images.
                if file_ext(path) not in extensions or not is_generic_name(path, patterns):
                    continue
                stat = path.lstat()
                if not stat_module.S_ISREG(stat.st_mode):
                    continue
                age_seconds = dt.datetime.now().timestamp() - stat.st_mtime
                if age_seconds < min_age * 60 or stat.st_size > max_bytes:
                    continue
                if str(path) in duplicate_sources:
                    continue
                if proposal_matches_source(path, recent_proposals.get(str(path))):
                    continue
                skip, _ = should_skip(path, cfg, root_cfg)
                if not skip:
                    found.append(path)
            except OSError:
                continue
    return sorted(found, key=lambda item: item.stat().st_mtime)


def run(
    config_path: Path,
    max_items: int | None = None,
    source_root: Path | None = None,
    include_opaque_ids: bool = False,
) -> int:
    cfg = load_config(config_path)
    local = cfg.get("local_naming", {})
    started = time.monotonic()
    max_run_seconds = float(local.get("max_run_seconds", 1200))
    if source_root is not None:
        root = source_root.expanduser().resolve()
        cfg["allow_roots"] = [
            {
                "path": str(root),
                "clean_root": False,
                "move_directories": False,
                "rename_in_place_only": True,
            }
        ]
        local["rename_in_place_only"] = True
    if include_opaque_ids:
        patterns = local.setdefault("generic_name_patterns", [])
        opaque_pattern = r"(?-i:^(?=(?:.*[A-Z]){2})[A-Za-z0-9_-]{8,24}$)"
        if opaque_pattern not in patterns:
            patterns.append(opaque_pattern)
    limit = max_items if max_items is not None else int(local.get("max_items", 12))
    stamp = now_stamp()
    proposal_dir = Path(cfg["proposal_dir"]).expanduser()
    report_dir = Path(cfg["report_dir"]).expanduser()
    proposal_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = proposal_dir / f"{stamp}.jsonl"
    report_path = report_dir / f"{stamp}-local-naming.md"
    proposal_path.touch()
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    deadline_reached = False
    processed = 0

    selected = candidates(cfg)[:limit]
    with proposal_path.open("a", encoding="utf-8", buffering=1) as handle:
        for path in selected:
            if time.monotonic() - started >= max_run_seconds:
                deadline_reached = True
                break
            try:
                stat = path.stat()
                result, elapsed = ollama_classify(path, cfg)
                row = {
                    "source": str(path),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "sha256": sha256(path),
                    "suggested_name": result["suggested_name"],
                    "destination_key": result["destination_key"],
                    "name_confidence": result["name_confidence"],
                    "destination_confidence": result["destination_confidence"],
                    "confidence": min(result["name_confidence"], result["destination_confidence"]),
                    "summary": result["summary"],
                    "reason": result["reason"],
                    "model": result["model"],
                    "latency_seconds": round(elapsed, 3),
                    "time": stamp,
                }
                rows.append(row)
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
            except Exception as exc:
                errors.append({"source": str(path), "error": repr(exc)})
            finally:
                processed += 1

    deferred = len(selected) - processed

    if local.get("rename_in_place_only"):
        accepted = sum(
            float(row["name_confidence"])
            >= float(local.get("rename_name_confidence_threshold", 0.50))
            for row in rows
        )
    else:
        accepted = sum(
            1
            for row in rows
            if (
                (
                    row["destination_key"] == "resource:review"
                    and bool(local.get("auto_apply_review", False))
                    and float(row["name_confidence"])
                    >= float(local.get("review_name_confidence_threshold", 0.90))
                    and float(row["destination_confidence"])
                    >= float(local.get("review_destination_confidence_threshold", 0.75))
                )
                or (
                    row["destination_key"] != "resource:review"
                    and float(row["name_confidence"])
                    >= float(local.get("proposal_name_confidence_threshold", 0.90))
                    and float(row["destination_confidence"])
                    >= proposal_confidence_threshold(row["destination_key"], cfg)
                )
            )
        )
    review = len(rows) - accepted
    lines = [
        f"# Local PARA naming prep — {stamp}",
        "",
        f"Model: `{local.get('model', 'qwen3.6:35b-a3b')}`",
        "",
        f"- candidates: {len(selected)}",
        f"- proposals: {len(rows)}",
        f"- above confidence threshold: {accepted}",
        f"- needs review / below threshold: {review}",
        f"- errors: {len(errors)}",
        f"- deferred by runtime budget: {deferred}",
        "",
        "## Proposals",
        "",
    ]
    for row in rows:
        lines.append(
            f"- `{row['source']}` → `{row['suggested_name']}` / "
            f"`{row['destination_key']}` (name {row['name_confidence']:.2f}; "
            f"destination {row['destination_confidence']:.2f}; {row['summary']})"
        )
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{row['source']}`: {row['error']}" for row in errors)
    lines.extend(["", f"Proposal manifest: `{proposal_path}`", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "model": local.get("model", "qwen3.6:35b-a3b"),
        "candidates": len(selected),
        "proposals": len(rows),
        "accepted": accepted,
        "needs_review": review,
        "errors": len(errors),
        "deferred": deferred,
        "deadline_reached": deadline_reached,
        "proposal_manifest": str(proposal_path),
        "report": str(report_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--root", type=Path, help="scan only immediate children of this root")
    parser.add_argument(
        "--include-opaque-ids",
        action="store_true",
        help="treat short social/CDN-style opaque image IDs as generic names",
    )
    args = parser.parse_args()
    return run(
        Path(args.config).expanduser(),
        args.max_items,
        args.root,
        args.include_opaque_ids,
    )


if __name__ == "__main__":
    raise SystemExit(main())
