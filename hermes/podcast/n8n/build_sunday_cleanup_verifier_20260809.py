#!/usr/bin/env python3
"""Build the visible post-delete verifier for Sunday episode 126."""

from __future__ import annotations

import json
from pathlib import Path

from build_approved_duplicate_cleanup_20260808 import CLOUDINARY, GITHUB_HTTP, SUPABASE, code, connect, node


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-sunday-cleanup-verifier-2026-08-09.json"


def build() -> dict:
    filters = {"filterType": "manual", "matchType": "allFilters", "filters": {"conditions": [
        {"keyName": "date", "condition": "eq", "keyValue": "2026-08-09"},
        {"keyName": "episode", "condition": "eq", "keyValue": 126},
    ]}}
    nodes = [
        node("webhook", "Published Sunday Cleanup Verification Webhook", "n8n-nodes-base.webhook", 0, {"httpMethod": "POST", "path": "podcast-sunday-126-cleanup-verify-20260809", "responseMode": "onReceived", "options": {}}, typeVersion=2.1),
        code("context", "Exact Sunday Verification Context", 240, "return [{json:{date:'2026-08-09',episode:126,recoveryUrl:'https://res.cloudinary.com/ddicetqs5/video/upload/v1786286368/anitguru-trash/gurus-tech-bytes-2026-08-09-episode-126-deepseek-retest-backup.mp3',deleteCommitSha:'f2dac8b3d5f32a222edc8d96a55a68e188bda6e9'}}];"),
        node("verify_row", "Supabase - Verify Episode 126 Absent", "n8n-nodes-base.supabase", 480, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE, alwaysOutputData=True),
        node("verify_cloudinary", "Cloudinary - Verify Sunday Origin Placeholder", "n8n-nodes-cloudinary.cloudinary", 720, {"resource": "asset", "operation": "getAsset", "assetId": "c04a5d5ff68a9c35470cbc5789dcd2ea"}, typeVersion=2, credentials=CLOUDINARY, onError="continueRegularOutput"),
        node("verify_github", "Verify GitHub Sunday File Absent", "n8n-nodes-base.httpRequest", 960, {"url": "https://api.github.com/repos/anitguru/anit.guru/contents/content%2Fpodcast%2F2026-08-09.md?ref=main", "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "sendHeaders": True, "headerParameters": {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"}, {"name": "X-GitHub-Api-Version", "value": "2022-11-28"}]}, "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}, "timeout": 30000}}, typeVersion=4.4, credentials=GITHUB_HTTP, notes="HTTP exception: native GitHub Get File treats the expected 404 as an execution error."),
        code("gate", "Hard Sunday Three-System Absence Gate", 1200, r"""const db=$('Supabase - Verify Episode 126 Absent').first().json,cloud=$('Cloudinary - Verify Sunday Origin Placeholder').first().json,git=$input.first().json,c=$('Exact Sunday Verification Context').first().json;
if(db.episode||db.date)throw new Error('Sunday Supabase row still present');if(!cloud.error&&!(cloud.placeholder===true&&Number(cloud.bytes)===0&&cloud.backup===true))throw new Error('Sunday Cloudinary origin still present');if(Number(git.statusCode)!==404)throw new Error(`Sunday GitHub file status ${git.statusCode}`);return [{json:{cleanupValidated:true,supabaseAbsent:true,cloudinaryAbsent:true,githubAbsent:true,...c}}];"""),
        node("ledger", "Ledger - Sunday Cleanup Verified", "n8n-nodes-base.dataTable", 1440, {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "authorized-retest-cleanup/2026-08-09/126", "execution_id": "={{ $execution.id }}", "run_mode": "production-cleanup", "episode": 126, "episode_date": "2026-08-09", "stage": "sunday-original-removed", "status": "passed", "attempt": 2, "selected_stories_json": "", "script_sha256": "", "audio_sha256": "", "srt_sha256": "", "qa_json": "={{ JSON.stringify($json) }}", "artifact_urls_json": "={{ JSON.stringify({recovery:$json.recoveryUrl,deleteCommitSha:$json.deleteCommitSha}) }}", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1),
        code("return", "Return Sunday Cleanup Proof", 1680, "return [{json:$('Hard Sunday Three-System Absence Gate').first().json}];"),
    ]
    connections = {}
    for source, target in zip((item["name"] for item in nodes), (item["name"] for item in nodes[1:])):
        connect(connections, source, target)
    workflow = {"id": "pSunday126VerifyX8", "name": "WF-podcast-sunday-cleanup-verifier-2026-08-09", "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    raw = json.dumps(workflow).lower()
    if len(nodes) != 8 or "scheduletrigger" in raw or "ssh" in raw or sum(item["type"] == "n8n-nodes-base.httpRequest" for item in nodes) != 1:
        raise ValueError("Sunday verifier architecture guard failed")
    return workflow


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(OUTPUT)
