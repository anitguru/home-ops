#!/usr/bin/env python3
"""Build the exact visible Sunday episode-126 cleanup before its authorized retest."""

from __future__ import annotations

import json
from pathlib import Path

from build_approved_duplicate_cleanup_20260808 import build as build_base


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-sunday-retest-cleanup-2026-08-09.json"
WORKFLOW_ID = "pSunday126CleanupX8"
WORKFLOW_NAME = "WF-podcast-sunday-retest-cleanup-2026-08-09"


def replace_strings(value):
    if isinstance(value, str):
        return (
            value.replace("2026-08-08", "2026-08-09")
            .replace("v1786183716", "v1786269857")
            .replace("episode 125", "episode 126")
            .replace("Episode 125", "Episode 126")
            .replace("episode-125", "episode-126")
            .replace("!==125", "!==126")
            .replace("\"episode\":125", "\"episode\":126")
            .replace("approved duplicate", "authorized Sunday retest")
            .replace("Approved Duplicate", "Authorized Sunday Retest")
            .replace("duplicate", "Sunday original")
            .replace("Duplicate", "Sunday Original")
        )
    if isinstance(value, list):
        return [replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {replace_strings(key): replace_strings(item) for key, item in value.items()}
    return value


def build() -> dict:
    workflow = replace_strings(build_base())
    workflow.update({"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False})
    workflow["settings"]["availableInMCP"] = True

    trigger = workflow["nodes"][0]
    old_trigger_name = trigger["name"]
    trigger.update({
        "id": "webhook",
        "name": "Published Sunday Cleanup Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2.1,
        "parameters": {
            "httpMethod": "POST",
            "path": "podcast-sunday-126-retest-cleanup-20260809",
            "responseMode": "onReceived",
            "options": {},
        },
    })
    workflow["connections"][trigger["name"]] = workflow["connections"].pop(old_trigger_name)

    context = {
        "approved": True,
        "date": "2026-08-09",
        "episode": 126,
        "audioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786269857/anitguru/gurus-tech-bytes-2026-08-09.mp3",
        "cloudinaryPublicId": "anitguru/gurus-tech-bytes-2026-08-09",
        "cloudinaryBackupPublicId": "anitguru-trash/gurus-tech-bytes-2026-08-09-episode-126-deepseek-retest-backup",
        "githubPath": "content/podcast/2026-08-09.md",
    }
    by_name = {item["name"]: item for item in workflow["nodes"]}
    by_name["Approved Cleanup Context"]["parameters"]["jsCode"] = (
        "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];"
    )
    backup = next(item for item in workflow["nodes"] if item["id"] == "backup_audio")
    backup["parameters"]["additionalFields"] = {
        "folder": "anitguru-trash",
        "public_id": "gurus-tech-bytes-2026-08-09-episode-126-deepseek-retest-backup",
        "tags": "authorized-retest-backup,episode-126",
    }
    cloudinary_verify = next(item for item in workflow["nodes"] if item["id"] == "verify_cloudinary")
    cloudinary_verify["parameters"]["assetId"] = "c04a5d5ff68a9c35470cbc5789dcd2ea"
    next(item for item in workflow["nodes"] if item["id"] == "delete_github")["parameters"]["commitMessage"] = (
        "cleanup: remove episode 126 before authorized DeepSeek retest"
    )
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("2026-08-08", "episode 125", "episode-125", "v1786183716", "10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger", "executeworkflowtrigger"):
        if forbidden in raw:
            raise ValueError(f"Sunday cleanup contains forbidden or stale value: {forbidden}")
    if workflow["active"] or len(workflow["nodes"]) != 21:
        raise ValueError("Sunday cleanup must be inactive and exactly 21 nodes")
    if workflow["nodes"][0]["type"] != "n8n-nodes-base.webhook" or not workflow["settings"].get("availableInMCP"):
        raise ValueError("Sunday cleanup must have a publishable MCP webhook trigger")
    http_nodes = [item for item in workflow["nodes"] if item["type"] == "n8n-nodes-base.httpRequest"]
    if len(http_nodes) != 1 or not http_nodes[0].get("notes", "").startswith("HTTP exception:"):
        raise ValueError("only documented GitHub absence verification may use HTTP")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code" and len([line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]) > 12:
            raise ValueError(f"Sunday cleanup Code node too large: {item['name']}")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
