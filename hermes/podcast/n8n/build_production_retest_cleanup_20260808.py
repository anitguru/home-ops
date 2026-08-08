#!/usr/bin/env python3
"""Build the exact visible cleanup required before the final clean production retest."""

from __future__ import annotations

import json
from pathlib import Path

import build_approved_duplicate_cleanup_20260808 as base


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-production-retest-cleanup-2026-08-08.json"


def build() -> dict:
    workflow = base.build()
    workflow["id"] = "pProdRetestCleanX8"
    workflow["name"] = "WF-podcast-production-retest-cleanup-2026-08-08"
    # This approved one-shot cleanup is retained as auditable recovery history,
    # but should not remain exposed as a routine MCP action after the retest.
    workflow["settings"]["availableInMCP"] = False
    by_id = {node["id"]: node for node in workflow["nodes"]}
    context = {
        "approved": True,
        "date": "2026-08-08",
        "episode": 125,
        "audioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786230258/anitguru/gurus-tech-bytes-2026-08-08.mp3",
        "cloudinaryPublicId": "anitguru/gurus-tech-bytes-2026-08-08",
        "cloudinaryBackupPublicId": "anitguru-trash/gurus-tech-bytes-2026-08-08-episode-125-retest-backup",
        "githubPath": "content/podcast/2026-08-08.md",
    }
    by_id["context"]["parameters"]["jsCode"] = "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];"
    by_id["context"]["notes"] = "Exact operator-approved cleanup before the final corrected production retest."
    upload = by_id["backup_audio"]["parameters"]["additionalFields"]
    upload["public_id"] = "gurus-tech-bytes-2026-08-08-episode-125-retest-backup"
    upload["tags"] = "approved-production-retest-backup,episode-125"
    by_id["delete_github"]["parameters"]["commitMessage"] = "cleanup: prepare exact episode 125 production retest"
    for node in workflow["nodes"]:
        raw = json.dumps(node)
        raw = raw.replace("approved-cleanup/2026-08-08/125", "production-retest-cleanup/2026-08-08/125")
        rebuilt = json.loads(raw)
        node.clear()
        node.update(rebuilt)
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger", "executeworkflowtrigger"):
        if forbidden in raw:
            raise ValueError(f"retest cleanup contains forbidden capability: {forbidden}")
    if workflow["active"] or len(workflow["nodes"]) != 21:
        raise ValueError("retest cleanup must be inactive and exactly bounded")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
