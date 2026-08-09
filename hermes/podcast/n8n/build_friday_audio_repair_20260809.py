#!/usr/bin/env python3
"""Build the exact visible Friday episode-124 audio replacement workflow."""

from __future__ import annotations

import json
from pathlib import Path

from build_portable_staging_v1 import (
    CLOUDINARY_CREDENTIAL,
    GITHUB_NATIVE_CREDENTIAL,
    code_node,
    node,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-friday-audio-repair-2026-08-09.json"
WORKFLOW_ID = "pFriday124RepairX8"
WORKFLOW_NAME = "WF-podcast-friday-audio-repair-2026-08-09"
MEDIA_ID = "pMediaSubX8Q3M7"
SUPABASE = {"supabaseApi": {"id": "duPN6Njb1go7DN8w", "name": "Supabase (podcast)"}}


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    context = {
        "approved": True,
        "date": "2026-08-07",
        "episode": 124,
        "runMode": "production",
        "runId": "friday-audio-repair/2026-08-07/124",
        "githubPath": "content/podcast/2026-08-07.md",
        "oldAudioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786096920/anitguru/gurus-tech-bytes-2026-08-07.mp3",
        "newCloudinaryPublicId": "anitguru/gurus-tech-bytes-2026-08-07-rerender",
    }
    filters = {"filterType": "manual", "matchType": "allFilters", "filters": {"conditions": [
        {"keyName": "date", "condition": "eq", "keyValue": "={{ $('Friday Repair Context').first().json.date }}"},
        {"keyName": "episode", "condition": "eq", "keyValue": "={{ $('Friday Repair Context').first().json.episode }}"},
    ]}}
    schema = [
        {"id": key, "displayName": key, "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": kind}
        for key, kind in (("runMode", "string"), ("date", "string"), ("runId", "string"), ("episode", "number"), ("selectedStories", "array"), ("scriptText", "string"), ("script_sha256", "string"))
    ]
    nodes = [
        node("webhook", "Published Friday Repair Webhook", "n8n-nodes-base.webhook", 0, {"httpMethod": "POST", "path": "podcast-friday-124-audio-repair-20260809", "responseMode": "onReceived", "options": {}}, typeVersion=2.1),
        code_node("context", "Friday Repair Context", 240, "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];", "Exact operator-approved episode-124 audio-only repair. The old asset remains as the recovery copy."),
        code_node("gate", "Hard Friday Exact-Target Gate", 480, r"""const c=$input.first().json;
if(c.approved!==true||c.date!=='2026-08-07'||c.episode!==124||c.runMode!=='production')throw new Error('Friday repair target mismatch');
if(c.githubPath!=='content/podcast/2026-08-07.md'||c.newCloudinaryPublicId!=='anitguru/gurus-tech-bytes-2026-08-07-rerender')throw new Error('Friday artifact target mismatch');return [{json:c}];"""),
        node("github_get", "GitHub - Read Friday Episode File", "n8n-nodes-base.github", 720, {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Friday Repair Context').first().json.githubPath }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}}, typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL),
        code_node("parse", "Recover Friday Transcript + Steer Episode Number", 960, r"""const f=$input.first().json,c=$('Friday Repair Context').first().json;
const raw=Buffer.from(String(f.content||'').replace(/\n/g,''),'base64').toString('utf8');const parts=raw.split(/^---\s*$/m);const body=(parts.slice(2).join('---')).trim();
if(f.path!==c.githubPath||!raw.includes('episode: 124')||!raw.includes(c.oldAudioUrl)||!body.startsWith("Good morning, it's Friday."))throw new Error('Friday GitHub source mismatch');
const scriptText=body.replace("This is Guru's Tech Bytes, episode 124.","This is Guru's Tech Bytes, episode one hundred twenty four.");
if(scriptText===body||scriptText.split(/\n\s*\n/).length!==6||/\d/.test(scriptText.split(/\n\s*\n/)[0]))throw new Error('Friday spoken-number steering failed');return [{json:{...c,rawMarkdown:raw,scriptText,githubSourceSha:f.sha}}];"""),
        node("supabase_get", "Supabase - Read Exact Friday Row", "n8n-nodes-base.supabase", 1200, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE),
        code_node("validate_row", "Validate Friday Source Row", 1440, r"""const r=$input.first().json,c=$('Recover Friday Transcript + Steer Episode Number').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==c.oldAudioUrl||!Array.isArray(r.stories)||r.stories.length!==4)throw new Error('Friday Supabase source mismatch');return [{json:{...c,selectedStories:r.stories}}];"""),
        node("script_hash", "SHA256 Friday Corrected Script", "n8n-nodes-base.crypto", 1680, {"action": "hash", "binaryData": False, "type": "SHA256", "value": "={{ $json.scriptText }}", "dataPropertyName": "script_sha256", "encoding": "hex"}, typeVersion=2),
        node("media", "Run Published Chatterbox Media Workflow", "n8n-nodes-base.executeWorkflow", 1920, {"source": "database", "workflowId": {"__rl": True, "value": MEDIA_ID, "mode": "list", "cachedResultName": "WF-podcast-sub-media-v1"}, "workflowInputs": {"mappingMode": "defineBelow", "value": {key: "={{ $json." + key + " }}" for key, _ in (("runMode", ""), ("date", ""), ("runId", ""), ("episode", ""), ("selectedStories", ""), ("scriptText", ""), ("script_sha256", ""))}, "matchingColumns": [], "schema": schema, "attemptToConvertTypes": False, "convertFieldsToString": False}, "mode": "once", "options": {"waitForSubWorkflow": True}}, typeVersion=1.3),
        code_node("validate_media", "Validate Friday Audio QA + Binary", 2160, r"""const i=$input.first(),r=i.json,q=r.audioQa||{};
if(r.mediaValidated!==true||!i.binary?.audio||q.duration_seconds<60||q.true_peak_dbtp>-1.5||q.clipped_samples!==0||q.long_silence_ratio>0.08)throw new Error('Friday media QA failed');return [i];"""),
        node("upload", "Cloudinary - Upload Friday Corrected Audio", "n8n-nodes-cloudinary.cloudinary", 2400, {"resource": "upload", "operation": "uploadFile", "file": "audio", "resource_type_file": "video", "additionalFieldsFile": {"folder": "anitguru", "public_id": "gurus-tech-bytes-2026-08-07-rerender", "tags": "podcast-production,episode-124-corrected"}}, typeVersion=2, credentials=CLOUDINARY_CREDENTIAL),
        code_node("validate_upload", "Validate Friday Cloudinary Replacement", 2640, r"""const r=$input.first().json,c=$('Friday Repair Context').first().json;
if(r.public_id!==c.newCloudinaryPublicId||Number(r.bytes)<100000||!String(r.secure_url||'').startsWith('https://res.cloudinary.com/'))throw new Error('Friday Cloudinary replacement invalid');return [{json:r}];"""),
        node("download", "Download Friday Replacement for Hash Proof", "n8n-nodes-base.httpRequest", 2880, {"url": "={{ $('Validate Friday Cloudinary Replacement').first().json.secure_url }}", "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "downloaded"}}, "timeout": 120000}}, typeVersion=4.4, notes="HTTP exception: the Cloudinary community node has no delivery-URL binary download operation."),
        node("download_hash", "SHA256 Downloaded Friday Replacement", "n8n-nodes-base.crypto", 3120, {"action": "hash", "binaryData": True, "binaryPropertyName": "downloaded", "type": "SHA256", "dataPropertyName": "downloaded_sha256", "encoding": "hex"}, typeVersion=2),
        code_node("validate_hash", "Validate Friday Download Hash", 3360, r"""const r=$input.first().json,e=$('Validate Friday Audio QA + Binary').first().json.audio_sha256;
if(r.downloaded_sha256!==e)throw new Error('Friday downloaded audio hash mismatch');return [{json:{audio_sha256:e,verified:true}}];"""),
        code_node("markdown", "Build Friday Markdown with Replacement Link", 3600, r"""const c=$('Recover Friday Transcript + Steer Episode Number').first().json,u=$('Validate Friday Cloudinary Replacement').first().json,m=$('Validate Friday Audio QA + Binary').first().json;
const duration=`${Math.floor(m.audioQa.duration_seconds/60)}:${String(Math.round(m.audioQa.duration_seconds%60)).padStart(2,'0')}`;let raw=c.rawMarkdown;
raw=raw.replace(/^audioUrl:.*$/m,`audioUrl: ${JSON.stringify(u.secure_url)}`).replace(/^audioLength:.*$/m,`audioLength: ${u.bytes}`).replace(/^duration:.*$/m,`duration: ${JSON.stringify(duration)}`);
const parts=raw.split(/^---\s*$/m);const markdown=`---${parts[1]}---\n\n${c.scriptText}\n`;return [{json:{markdown,duration,path:c.githubPath}}];"""),
        node("github_edit", "GitHub - Edit Friday Episode on Main", "n8n-nodes-base.github", 3840, {"resource": "file", "operation": "edit", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Build Friday Markdown with Replacement Link').first().json.path }}", "binaryData": False, "fileContent": "={{ $('Build Friday Markdown with Replacement Link').first().json.markdown }}", "commitMessage": "podcast: repair episode 124 spoken greeting and audio", "additionalParameters": {"branch": {"branch": "main"}}}, typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL),
        node("github_readback", "GitHub - Read Back Friday Repair", "n8n-nodes-base.github", 4080, {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Friday Repair Context').first().json.githubPath }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}}, typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL),
        code_node("validate_github", "Validate Friday GitHub Readback", 4320, r"""const f=$input.first().json,e=$('Build Friday Markdown with Replacement Link').first().json,u=$('Validate Friday Cloudinary Replacement').first().json,g=$('GitHub - Edit Friday Episode on Main').first().json;
const raw=Buffer.from(String(f.content||'').replace(/\n/g,''),'base64').toString('utf8');if(raw!==e.markdown||!raw.includes(u.secure_url)||!raw.includes('episode one hundred twenty four.')||!/^[a-f0-9]{40}$/.test(String(g.commit?.sha||'')))throw new Error('Friday GitHub readback invalid');return [{json:{commitSha:g.commit.sha,contentSha:f.sha,verified:true}}];"""),
        code_node("prepare_update", "Prepare Friday Supabase Replacement", 4560, r"""const r=$('Validate Friday Source Row').first().json,u=$('Validate Friday Cloudinary Replacement').first().json,m=$('Validate Friday Audio QA + Binary').first().json;return [{json:{date:r.date,episode:r.episode,stories:r.selectedStories,audio_url:u.secure_url,duration_secs:Math.round(m.audioQa.duration_seconds)}}];"""),
        node("supabase_update", "Supabase - Update Friday Episode Row", "n8n-nodes-base.supabase", 4800, {"resource": "row", "operation": "update", "tableId": "podcast_episodes", "dataToSend": "autoMapInputData", "inputsToIgnore": "", **filters}, typeVersion=1, credentials=SUPABASE),
        node("supabase_readback", "Supabase - Read Back Friday Replacement", "n8n-nodes-base.supabase", 5040, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE),
        code_node("hard_gate", "Hard Friday Three-System Repair Gate", 5280, r"""const r=$input.first().json,c=$('Friday Repair Context').first().json,u=$('Validate Friday Cloudinary Replacement').first().json,g=$('Validate Friday GitHub Readback').first().json,h=$('Validate Friday Download Hash').first().json,m=$('Validate Friday Audio QA + Binary').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==u.secure_url||Number(r.duration_secs)!==Math.round(m.audioQa.duration_seconds)||g.verified!==true||h.verified!==true)throw new Error('Friday three-system repair proof failed');return [{json:{repairValidated:true,date:c.date,episode:c.episode,oldAudioUrl:c.oldAudioUrl,newAudioUrl:u.secure_url,bytes:u.bytes,durationSeconds:m.audioQa.duration_seconds,audioQa:m.audioQa,audio_sha256:h.audio_sha256,github:g,supabase:r}}];"""),
        node("ledger", "Ledger - Friday Audio Repair Complete", "n8n-nodes-base.dataTable", 5520, {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "friday-audio-repair/2026-08-07/124", "execution_id": "={{ $execution.id }}", "run_mode": "production-repair", "episode": 124, "episode_date": "2026-08-07", "stage": "audio-link-replaced", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($json.supabase.stories) }}", "script_sha256": "={{ $('SHA256 Friday Corrected Script').first().json.script_sha256 }}", "audio_sha256": "={{ $json.audio_sha256 }}", "srt_sha256": "", "qa_json": "={{ JSON.stringify($json.audioQa) }}", "artifact_urls_json": "={{ JSON.stringify({old:$json.oldAudioUrl,new:$json.newAudioUrl,github:$json.github}) }}", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1),
        code_node("return", "Return Friday Repair Contract", 5760, "return [{json:$('Hard Friday Three-System Repair Gate').first().json}];"),
    ]
    connections: dict = {}
    for source, target in zip((n["name"] for n in nodes), (n["name"] for n in nodes[1:])):
        connect(connections, source, target)
    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger"):
        if forbidden in raw:
            raise ValueError(f"Friday repair contains forbidden value: {forbidden}")
    if workflow["active"] or len(workflow["nodes"]) != 25:
        raise ValueError("Friday repair must be inactive and exactly bounded")
    http_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    if len(http_nodes) != 1 or not http_nodes[0].get("notes", "").startswith("HTTP exception:"):
        raise ValueError("Friday repair allows only documented Cloudinary delivery download HTTP")
    if not any(n["type"] == "n8n-nodes-base.github" and n["parameters"].get("operation") == "edit" for n in workflow["nodes"]):
        raise ValueError("native GitHub edit node missing")
    if not any(n["type"] == "n8n-nodes-base.supabase" and n["parameters"].get("operation") == "update" for n in workflow["nodes"]):
        raise ValueError("native Supabase update node missing")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code" and len([x for x in item["parameters"]["jsCode"].splitlines() if x.strip()]) > 14:
            raise ValueError(f"Friday repair Code node too large: {item['name']}")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
