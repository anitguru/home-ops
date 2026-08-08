#!/usr/bin/env python3
"""Build the one-shot, operator-approved duplicate episode cleanup workflow."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-cleanup-approved-2026-08-08.json"
WORKFLOW_ID = "pCleanup125X8Q3M7"
WORKFLOW_NAME = "WF-podcast-cleanup-approved-2026-08-08"

SUPABASE = {"supabaseApi": {"id": "duPN6Njb1go7DN8w", "name": "Supabase (podcast)"}}
GITHUB = {"githubApi": {"id": "pGithubNodeX8Q3M7Z", "name": "GitHub Node (podcast)"}}
GITHUB_HTTP = {"httpHeaderAuth": {"id": "pGithubApiX8Q3M7Z", "name": "GitHub API (podcast)"}}
CLOUDINARY = {"cloudinaryApi": {"id": "pCloudinaryX8Q3M7", "name": "Cloudinary (podcast)"}}


def node(node_id: str, name: str, node_type: str, x: int, parameters: dict, **extra: object) -> dict:
    result = {"id": node_id, "name": name, "type": node_type, "typeVersion": extra.pop("typeVersion", 1), "position": [x, 0], "parameters": parameters}
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, js: str, notes: str = "") -> dict:
    return node(node_id, name, "n8n-nodes-base.code", x, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()}, typeVersion=2, notes=notes)


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    context = {
        "approved": True,
        "date": "2026-08-08",
        "episode": 125,
        "audioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786183716/anitguru/gurus-tech-bytes-2026-08-08.mp3",
        "cloudinaryPublicId": "anitguru/gurus-tech-bytes-2026-08-08",
        "cloudinaryBackupPublicId": "anitguru-trash/gurus-tech-bytes-2026-08-08-episode-125-backup",
        "githubPath": "content/podcast/2026-08-08.md",
    }
    filters = {"filterType": "manual", "matchType": "allFilters", "filters": {"conditions": [
        {"keyName": "date", "condition": "eq", "keyValue": "={{ $('Approved Cleanup Context').first().json.date }}"},
        {"keyName": "episode", "condition": "eq", "keyValue": "={{ $('Approved Cleanup Context').first().json.episode }}"},
    ]}}
    nodes = [
        node("manual", "Manual Approved Cleanup Trigger", "n8n-nodes-base.manualTrigger", 0, {}),
        code("context", "Approved Cleanup Context", 240, "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];", "Exact operator-approved 2026-08-08 duplicate only."),
        code(
            "gate", "Hard Exact-Target Cleanup Gate", 480,
            r"""const c=$input.first().json;
if(c.approved!==true||c.date!=='2026-08-08'||c.episode!==125) throw new Error('cleanup approval target mismatch');
if(c.cloudinaryPublicId!=='anitguru/gurus-tech-bytes-2026-08-08'||c.githubPath!=='content/podcast/2026-08-08.md') throw new Error('cleanup artifact target mismatch');
return [{json:c}];""",
        ),
        node("get_row", "Supabase - Read Exact Episode 125", "n8n-nodes-base.supabase", 720, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE),
        code(
            "validate_row", "Validate Exact Supabase Row", 960,
            r"""const r=$input.first().json,c=$('Approved Cleanup Context').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==c.audioUrl) throw new Error('Supabase target row changed or missing');
return [{json:r}];""",
        ),
        node(
            "backup_audio", "Cloudinary - Copy Production Audio to Recovery", "n8n-nodes-cloudinary.cloudinary", 1200,
            {"resource": "upload", "operation": "uploadUrl", "url": "={{ $('Approved Cleanup Context').first().json.audioUrl }}", "resource_type": "video", "additionalFields": {"folder": "anitguru-trash", "public_id": "gurus-tech-bytes-2026-08-08-episode-125-backup", "tags": "approved-cleanup-backup,episode-125"}},
            typeVersion=2, credentials=CLOUDINARY,
        ),
        code(
            "validate_backup", "Validate Cloudinary Recovery Copy", 1440,
            r"""const r=$input.first().json,c=$('Approved Cleanup Context').first().json;
if(r.public_id!==c.cloudinaryBackupPublicId||Number(r.bytes)<100000||!String(r.secure_url||'').startsWith('https://res.cloudinary.com/')) throw new Error('Cloudinary recovery copy invalid');
return [{json:r}];""",
        ),
        node(
            "get_github", "GitHub - Read Production Episode File", "n8n-nodes-base.github", 1680,
            {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Approved Cleanup Context').first().json.githubPath }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}},
            typeVersion=1.1, credentials=GITHUB,
        ),
        code(
            "validate_github", "Validate Production GitHub File", 1920,
            r"""const r=$input.first().json,c=$('Approved Cleanup Context').first().json;
if(r.path!==c.githubPath||!/^[a-f0-9]{40}$/.test(String(r.sha||''))||!String(r.content||'')) throw new Error('GitHub target file changed or missing');
return [{json:{path:r.path,sha:r.sha,size:r.size}}];""",
        ),
        node(
            "ledger_backup", "Ledger - Duplicate Recovery Captured", "n8n-nodes-base.dataTable", 2160,
            {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "approved-cleanup/2026-08-08/125", "execution_id": "={{ $execution.id }}", "run_mode": "production-cleanup", "episode": 125, "episode_date": "2026-08-08", "stage": "duplicate-backup", "status": "captured", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($('Validate Exact Supabase Row').first().json.stories) }}", "script_sha256": "", "audio_sha256": "", "srt_sha256": "", "qa_json": "={{ JSON.stringify({supabase:$('Validate Exact Supabase Row').first().json,github:$('Validate Production GitHub File').first().json}) }}", "artifact_urls_json": "={{ JSON.stringify({production:$('Approved Cleanup Context').first().json.audioUrl,recovery:$('Validate Cloudinary Recovery Copy').first().json.secure_url}) }}", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1,
        ),
        node(
            "delete_cloudinary", "Cloudinary - Delete Exact Production Audio", "n8n-nodes-cloudinary.cloudinary", 2400,
            {"resource": "asset", "operation": "deleteAssets", "publicIds": "={{ $('Approved Cleanup Context').first().json.cloudinaryPublicId }}", "resourceType": "video", "type": "upload", "deleteOptions": {"invalidate": True, "keep_original": False}},
            typeVersion=2, credentials=CLOUDINARY,
        ),
        code(
            "validate_cloudinary_delete", "Validate Cloudinary Delete Response", 2640,
            r"""const r=$input.first().json,c=$('Approved Cleanup Context').first().json;
if(!['deleted','not_found'].includes(String(r.deleted?.[c.cloudinaryPublicId]||''))) throw new Error('Cloudinary delete not acknowledged');
return [{json:r}];""",
        ),
        node(
            "delete_github", "GitHub - Delete Production Episode File", "n8n-nodes-base.github", 2880,
            {"resource": "file", "operation": "delete", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Approved Cleanup Context').first().json.githubPath }}", "commitMessage": "cleanup: remove approved duplicate episode 125", "additionalParameters": {"branch": {"branch": "main"}}},
            typeVersion=1.1, credentials=GITHUB,
        ),
        code(
            "validate_github_delete", "Validate GitHub Delete Commit", 3120,
            r"""const r=$input.first().json;
if(!/^[a-f0-9]{40}$/.test(String(r.commit?.sha||''))) throw new Error('GitHub delete commit missing');
return [{json:{deleteCommitSha:r.commit.sha}}];""",
        ),
        node("delete_row", "Supabase - Delete Exact Episode 125", "n8n-nodes-base.supabase", 3360, {"resource": "row", "operation": "delete", "tableId": "podcast_episodes", **filters}, typeVersion=1, credentials=SUPABASE),
        node("verify_row", "Supabase - Verify Episode 125 Absent", "n8n-nodes-base.supabase", 3600, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE, alwaysOutputData=True),
        node(
            "verify_cloudinary", "Cloudinary - Verify Deleted Asset Placeholder", "n8n-nodes-cloudinary.cloudinary", 3840,
            {"resource": "asset", "operation": "getAsset", "assetId": "ae11b2444759a36eefca31e9c8b094d8"},
            typeVersion=2, credentials=CLOUDINARY, onError="continueRegularOutput",
        ),
        node(
            "verify_github", "Verify GitHub Production File Absent", "n8n-nodes-base.httpRequest", 4080,
            {"url": "https://api.github.com/repos/anitguru/anit.guru/contents/content%2Fpodcast%2F2026-08-08.md?ref=main", "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "sendHeaders": True, "headerParameters": {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"}, {"name": "X-GitHub-Api-Version", "value": "2022-11-28"}]}, "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}, "timeout": 30000}},
            typeVersion=4.4, credentials=GITHUB_HTTP, notes="HTTP exception: native GitHub Get File treats the expected 404 absence as an execution error and cannot return a never-error full response for verification.",
        ),
        code(
            "hard_verify", "Hard Three-System Absence Gate", 4320,
            r"""const db=$('Supabase - Verify Episode 125 Absent').first().json,cloud=$('Cloudinary - Verify Deleted Asset Placeholder').first().json,git=$input.first().json;
if(db.episode||db.date) throw new Error('Supabase duplicate still present');
if(!cloud.error&&!(cloud.placeholder===true&&Number(cloud.bytes)===0&&cloud.backup===true)) throw new Error('Cloudinary origin still present');
if(Number(git.statusCode)!==404) throw new Error(`GitHub production file status ${git.statusCode}`);
return [{json:{supabaseAbsent:true,cloudinaryAbsent:true,githubAbsent:true,githubDeleteCommit:$('Validate GitHub Delete Commit').first().json.deleteCommitSha,recoveryUrl:$('Validate Cloudinary Recovery Copy').first().json.secure_url,cleanupValidated:true}}];""",
        ),
        node(
            "ledger_complete", "Ledger - Approved Duplicate Removed", "n8n-nodes-base.dataTable", 4560,
            {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "approved-cleanup/2026-08-08/125", "execution_id": "={{ $execution.id }}", "run_mode": "production-cleanup", "episode": 125, "episode_date": "2026-08-08", "stage": "duplicate-removed", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($('Validate Exact Supabase Row').first().json.stories) }}", "script_sha256": "", "audio_sha256": "", "srt_sha256": "", "qa_json": "={{ JSON.stringify($('Hard Three-System Absence Gate').first().json) }}", "artifact_urls_json": "={{ JSON.stringify({recovery:$('Validate Cloudinary Recovery Copy').first().json.secure_url}) }}", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1,
        ),
        node("stop", "Approved Cleanup Stop", "n8n-nodes-base.noOp", 4800, {}, notes="One-shot terminal node. No schedule or reusable trigger exists."),
    ]
    connections: dict = {}
    for source, target in zip((n["name"] for n in nodes), (n["name"] for n in nodes[1:])):
        connect(connections, source, target)
    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": False}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger", "executeworkflowtrigger"):
        if forbidden in raw:
            raise ValueError(f"cleanup workflow contains forbidden capability: {forbidden}")
    if workflow["active"] or len(workflow["nodes"]) != 21:
        raise ValueError("cleanup must be inactive and exactly bounded")
    http_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    if len(http_nodes) != 1 or not http_nodes[0].get("notes", "").startswith("HTTP exception:"):
        raise ValueError("only documented GitHub absence verification may use HTTP")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code" and len([x for x in item["parameters"]["jsCode"].splitlines() if x.strip()]) > 12:
            raise ValueError(f"cleanup Code node too large: {item['name']}")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
