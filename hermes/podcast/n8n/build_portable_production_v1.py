#!/usr/bin/env python3
"""Build the visible manual-production distribution sub-workflow."""

from __future__ import annotations

import json
from pathlib import Path

from build_portable_staging_v1 import (
    CLOUDINARY_CREDENTIAL,
    GITHUB_HTTP_CREDENTIAL,
    GITHUB_NATIVE_CREDENTIAL,
    TELEGRAM_CREDENTIAL,
    code_node,
    ledger_node as staging_ledger_node,
    node,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-portable-production-v1.json"
WORKFLOW_ID = "pPortableProdX8Q3M7"
WORKFLOW_NAME = "WF-podcast-portable-production-v1"
SUPABASE_CREDENTIAL = {"supabaseApi": {"id": "duPN6Njb1go7DN8w", "name": "Supabase (podcast)"}}


def ledger_node(node_id: str, name: str, x: int, stage: str, status: str, **fields: str) -> dict:
    result = staging_ledger_node(node_id, name, x, stage, status, **fields)
    values = result["parameters"]["columns"]["value"]
    for key, value in values.items():
        if isinstance(value, str):
            values[key] = value.replace("Portable Staging Context", "Prepare Production Distribution Context").replace(".json.portableRunId", ".json.runId")
    values["run_mode"] = "production-manual"
    return result


def connect(connections: dict, source: str, target: str, target_input: int = 0) -> None:
    connections.setdefault(source, {"main": [[]]})["main"][0].append(
        {"node": target, "type": "main", "index": target_input}
    )


def build() -> dict:
    filters = {
        "filterType": "manual",
        "matchType": "allFilters",
        "filters": {"conditions": [{"keyName": "date", "condition": "eq", "keyValue": "={{ $('Prepare Production Distribution Context').first().json.date }}"}]},
    }
    nodes = [
        node(
            "sub_trigger", "When Called by Manual Production Parent", "n8n-nodes-base.executeWorkflowTrigger", 0,
            {"inputSource": "jsonExample", "jsonExample": json.dumps({"runMode": "shadow", "publishMode": "production", "manualProductionApproved": True, "date": "2026-08-08", "runId": "portable-production/2026-08-08/example", "episode": 125, "selectedStories": [], "scriptText": "approved", "script_sha256": "0" * 64, "audio_sha256": "0" * 64, "audioQa": {"duration_seconds": 120}, "srt_sha256": "0" * 64, "alignment": {}, "transcriptionValidated": True}, indent=2)},
            typeVersion=1.2,
        ),
        code_node(
            "context", "Prepare Production Distribution Context", 240,
            r"""const i=$input.first();const r=i.json;
if(!i.binary?.audio||!i.binary?.srt) throw new Error('production audio/SRT binaries missing');
const seconds=Number(r.audioQa?.duration_seconds);const duration=`${Math.floor(seconds/60)}:${String(Math.round(seconds%60)).padStart(2,'0')}`;
return [{json:{...r,startedAt:$now.toISO(),audio:{sha256:r.audio_sha256,bytes:0,durationSeconds:seconds,duration},srt:{sha256:r.srt_sha256,alignment:r.alignment}},binary:{audio:i.binary.audio,srt:i.binary.srt}}];""",
        ),
        code_node(
            "gate", "Hard Manual Production Authorization Gate", 480,
            r"""const r=$input.first().json;const et=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const failures=[];if(r.runMode!=='shadow')failures.push('generation mode');if(r.publishMode!=='production')failures.push('publish mode');if(r.manualProductionApproved!==true)failures.push('operator approval');if(r.date!==et)failures.push('ET date');
if(!/^portable-production\/\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]+$/.test(String(r.runId||'')))failures.push('run ID');if(r.transcriptionValidated!==true)failures.push('transcription proof');if(failures.length)throw new Error(`production gate: ${failures.join(', ')}`);return [{json:r}];""",
            "Explicit one-shot gate: current ET date, production publish mode, operator authorization, and completed transcription proof are all required.",
        ),
        ledger_node("ledger_start", "Ledger - Production Distribution Started", 720, "production-start", "running"),
        node(
            "supabase_absence", "Supabase - Confirm Today's Episode Absent", "n8n-nodes-base.supabase", 960,
            {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters},
            typeVersion=1, credentials=SUPABASE_CREDENTIAL, alwaysOutputData=True,
        ),
        code_node(
            "validate_db_absence", "Gate - Supabase Date Must Be Empty", 1200,
            r"""const r=$input.first().json;if(r.date||r.episode)throw new Error('production date already exists in Supabase');return [{json:$('Hard Manual Production Authorization Gate').first().json}];""",
        ),
        node(
            "github_absence", "GitHub - Confirm Production Page Absent", "n8n-nodes-base.httpRequest", 1440,
            {"url": "={{ 'https://api.github.com/repos/anitguru/anit.guru/contents/content%2Fpodcast%2F' + $json.date + '.md?ref=main' }}", "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "sendHeaders": True, "headerParameters": {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"}, {"name": "X-GitHub-Api-Version", "value": "2022-11-28"}]}, "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}, "timeout": 30000}},
            typeVersion=4.4, credentials=GITHUB_HTTP_CREDENTIAL,
            notes="HTTP exception: native GitHub Get File turns the required 404 precondition into an execution error and cannot return a never-error full response.",
        ),
        code_node(
            "validate_git_absence", "Gate - GitHub Page Must Be Empty", 1680,
            r"""const r=$input.first().json;if(Number(r.statusCode)!==404)throw new Error(`production GitHub page precondition returned ${r.statusCode}`);const c=$('Prepare Production Distribution Context').first();return [{json:c.json,binary:c.binary}];""",
        ),
        code_node(
            "restore_audio", "Restore Production Audio + SRT Binaries", 1920,
            r"""const c=$('Prepare Production Distribution Context').first();return [{json:c.json,binary:{audio:c.binary.audio,srt:c.binary.srt}}];""",
        ),
        node(
            "hash_audio", "SHA256 Production Audio", "n8n-nodes-base.crypto", 2160,
            {"action": "hash", "binaryData": True, "binaryPropertyName": "audio", "type": "SHA256", "dataPropertyName": "audio_sha256", "encoding": "hex"},
            typeVersion=2,
        ),
        code_node(
            "validate_audio", "Validate Exact Production Audio Hash", 2400,
            r"""const r=$input.first().json,e=$('Prepare Production Distribution Context').first().json.audio.sha256;if(r.audio_sha256!==e)throw new Error('production audio hash mismatch');return [{json:{audio_sha256:r.audio_sha256,verified:true}}];""",
        ),
        node("merge_audio", "Merge Production Binary + Verified Hash", "n8n-nodes-base.merge", 2640, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        node(
            "upload_audio", "Cloudinary - Upload Production Audio", "n8n-nodes-cloudinary.cloudinary", 2880,
            {"resource": "upload", "operation": "uploadFile", "file": "audio", "resource_type_file": "video", "additionalFieldsFile": {"folder": "anitguru", "public_id": "={{ 'gurus-tech-bytes-' + $('Prepare Production Distribution Context').first().json.date }}", "tags": "podcast-production,portable-n8n"}},
            typeVersion=2, credentials=CLOUDINARY_CREDENTIAL,
        ),
        code_node(
            "validate_upload", "Validate Production Cloudinary Upload", 3120,
            r"""const r=$input.first().json,c=$('Prepare Production Distribution Context').first().json,target=`anitguru/gurus-tech-bytes-${c.date}`;
if(r.public_id!==target||Number(r.bytes)<100000||!String(r.secure_url||'').startsWith('https://res.cloudinary.com/'))throw new Error('production Cloudinary upload invalid');return [{json:{...r,targetKey:target,audioSha256:c.audio.sha256}}];""",
        ),
        node(
            "head_audio", "HEAD Verify Production Audio", "n8n-nodes-base.httpRequest", 3360,
            {"method": "HEAD", "url": "={{ $('Validate Production Cloudinary Upload').first().json.secure_url }}", "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}}, "timeout": 20000}},
            typeVersion=4.4, notes="HTTP exception: the verified Cloudinary node has no delivery-URL HEAD operation.",
        ),
        code_node(
            "validate_head", "Validate Production Audio Delivery", 3600,
            r"""const r=$input.first().json;if(Number(r.statusCode)<200||Number(r.statusCode)>=400)throw new Error(`production audio HEAD ${r.statusCode}`);return [{json:{statusCode:r.statusCode,verified:true}}];""",
        ),
        ledger_node("ledger_cloudinary", "Ledger - Production Cloudinary Verified", 3840, "production-cloudinary", "passed", audio_sha256="={{ $('Prepare Production Distribution Context').first().json.audio.sha256 }}", artifact_urls_json="={{ JSON.stringify({audio:$('Validate Production Cloudinary Upload').first().json.secure_url}) }}"),
        code_node(
            "markdown", "Generate Production Episode Markdown", 4080,
            r"""const c=$('Prepare Production Distribution Context').first().json,u=$('Validate Production Cloudinary Upload').first().json;const clean=v=>String(v??'').replace(/\s+/g,' ').trim();
const title=`${clean(c.selectedStories[0]?.title)||"Guru's Tech Bytes"} | EP #${c.episode}`;const stories=c.selectedStories.map(s=>`  - title: ${JSON.stringify(clean(s.title))}\n    url: ${JSON.stringify(s.url)}\n    hnUrl: ${JSON.stringify(s.hnUrl)}\n    score: ${Number(s.score)}`).join('\n');
const markdown=`---\ntitle: ${JSON.stringify(title)}\nepisode: ${c.episode}\ndate: ${JSON.stringify(c.date)}\naudioUrl: ${JSON.stringify(u.secure_url)}\naudioLength: ${u.bytes}\nduration: ${JSON.stringify(c.audio.duration)}\nstories:\n${stories}\n---\n\n${c.scriptText.trim()}\n`;return [{json:{markdown,path:`content/podcast/${c.date}.md`}}];""",
        ),
        node(
            "github_create", "GitHub - Create Production Episode on Main", "n8n-nodes-base.github", 4320,
            {"resource": "file", "operation": "create", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Generate Production Episode Markdown').first().json.path }}", "binaryData": False, "fileContent": "={{ $('Generate Production Episode Markdown').first().json.markdown }}", "commitMessage": "={{ 'podcast: publish portable episode ' + $('Prepare Production Distribution Context').first().json.date }}", "additionalParameters": {"branch": {"branch": "main"}}},
            typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL,
        ),
        node(
            "github_get", "GitHub - Read Production Episode from Main", "n8n-nodes-base.github", 4560,
            {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Generate Production Episode Markdown').first().json.path }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}},
            typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL,
        ),
        code_node(
            "validate_github", "Validate Production GitHub Readback", 4800,
            r"""const f=$input.first().json,e=$('Generate Production Episode Markdown').first().json,c=$('GitHub - Create Production Episode on Main').first().json,d=Buffer.from(String(f.content||'').replace(/\n/g,''),'base64').toString('utf8');
if(f.path!==e.path||d!==e.markdown||!/^[a-f0-9]{40}$/.test(String(c.commit?.sha||'')))throw new Error('production GitHub readback invalid');return [{json:{branch:'main',path:f.path,commitSha:c.commit.sha,contentSha:f.sha,verified:true}}];""",
        ),
        ledger_node("ledger_github", "Ledger - Production GitHub Verified", 5040, "production-github", "passed", audio_sha256="={{ $('Prepare Production Distribution Context').first().json.audio.sha256 }}", artifact_urls_json="={{ JSON.stringify({audio:$('Validate Production Cloudinary Upload').first().json.secure_url,github:$('Validate Production GitHub Readback').first().json}) }}"),
        code_node(
            "db_row", "Prepare Native Supabase Episode Row", 5280,
            r"""const c=$('Prepare Production Distribution Context').first().json;return [{json:{date:c.date,episode:c.episode,stories:c.selectedStories,audio_url:$('Validate Production Cloudinary Upload').first().json.secure_url,duration_secs:Math.round(c.audio.durationSeconds)}}];""",
        ),
        node(
            "supabase_create", "Supabase - Create Production Episode Row", "n8n-nodes-base.supabase", 5520,
            {"resource": "row", "operation": "create", "tableId": "podcast_episodes", "dataToSend": "autoMapInputData", "inputsToIgnore": ""},
            typeVersion=1, credentials=SUPABASE_CREDENTIAL,
        ),
        node(
            "supabase_get", "Supabase - Read Back Production Episode", "n8n-nodes-base.supabase", 5760,
            {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters},
            typeVersion=1, credentials=SUPABASE_CREDENTIAL,
        ),
        code_node(
            "validate_db", "Validate Production Supabase Readback", 6000,
            r"""const r=$input.first().json,c=$('Prepare Production Distribution Context').first().json,u=$('Validate Production Cloudinary Upload').first().json;if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==u.secure_url||!Array.isArray(r.stories)||r.stories.length!==4||Number(r.duration_secs)!==Math.round(c.audio.durationSeconds))throw new Error('production Supabase readback invalid');return [{json:{row:r,verified:true}}];""",
        ),
        ledger_node("ledger_db", "Ledger - Production Supabase Verified", 6240, "production-database", "passed", audio_sha256="={{ $('Prepare Production Distribution Context').first().json.audio.sha256 }}", artifact_urls_json="={{ JSON.stringify({audio:$('Validate Production Cloudinary Upload').first().json.secure_url}) }}"),
        code_node(
            "notification", "Prepare Production Notification", 6480,
            r"""const c=$('Prepare Production Distribution Context').first().json,u=$('Validate Production Cloudinary Upload').first().json;return [{json:{text:`🎙️ Guru's Tech Bytes EP #${c.episode} is live — ${c.date}\n${u.secure_url}`}}];""",
        ),
        node("telegram_text", "Telegram - Send Production Summary", "n8n-nodes-base.telegram", 6720, {"resource": "message", "operation": "sendMessage", "chatId": "8100669692", "text": "={{ $json.text }}", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("restore_notify_audio", "Restore Audio for Telegram", 6960, r"""const c=$('Prepare Production Distribution Context').first();return [{json:{},binary:{audio:c.binary.audio}}];"""),
        node("telegram_audio", "Telegram - Send Production MP3", "n8n-nodes-base.telegram", 7200, {"resource": "message", "operation": "sendAudio", "chatId": "8100669692", "binaryData": True, "binaryPropertyName": "audio", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("restore_notify_srt", "Restore SRT for Telegram", 7440, r"""const c=$('Prepare Production Distribution Context').first();return [{json:{},binary:{srt:c.binary.srt}}];"""),
        node("telegram_srt", "Telegram - Send Production SRT", "n8n-nodes-base.telegram", 7680, {"resource": "message", "operation": "sendDocument", "chatId": "8100669692", "binaryData": True, "binaryPropertyName": "srt", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node(
            "validate_notifications", "Validate Production Telegram Delivery", 7920,
            r"""const ids=[$('Telegram - Send Production Summary').first().json.result?.message_id,$('Telegram - Send Production MP3').first().json.result?.message_id,$input.first().json.result?.message_id];if(ids.some(x=>!Number.isInteger(x)||x<1))throw new Error('production Telegram delivery missing');return [{json:{messageIds:ids,verified:true}}];""",
        ),
        ledger_node("ledger_complete", "Ledger - Manual Production Complete", 8160, "production-complete", "passed", audio_sha256="={{ $('Prepare Production Distribution Context').first().json.audio.sha256 }}", srt_sha256="={{ $('Prepare Production Distribution Context').first().json.srt.sha256 }}", qa_json="={{ JSON.stringify({audio:$('Prepare Production Distribution Context').first().json.audio,srt:$('Prepare Production Distribution Context').first().json.srt.alignment}) }}", artifact_urls_json="={{ JSON.stringify({audio:$('Validate Production Cloudinary Upload').first().json.secure_url,github:$('Validate Production GitHub Readback').first().json,telegram:$('Validate Production Telegram Delivery').first().json.messageIds}) }}"),
        code_node(
            "return_contract", "Return Production Distribution Contract", 8400,
            r"""const c=$('Prepare Production Distribution Context').first().json,u=$('Validate Production Cloudinary Upload').first().json,g=$('Validate Production GitHub Readback').first().json,n=$('Validate Production Telegram Delivery').first().json;return [{json:{runMode:c.runMode,publishMode:'production',date:c.date,runId:c.runId,episode:c.episode,audio_sha256:c.audio.sha256,srt_sha256:c.srt.sha256,cloudinary:{publicId:u.public_id,secureUrl:u.secure_url,bytes:u.bytes},github:g,supabasePersisted:true,telegramMessageIds:n.messageIds,distributionValidated:true}}];""",
        ),
    ]

    connections: dict = {}
    linear = [n["name"] for n in nodes[:9]]
    for source, target in zip(linear, linear[1:]):
        connect(connections, source, target)
    connections["Restore Production Audio + SRT Binaries"] = {"main": [[
        {"node": "SHA256 Production Audio", "type": "main", "index": 0},
        {"node": "Merge Production Binary + Verified Hash", "type": "main", "index": 0},
    ]]}
    connect(connections, "SHA256 Production Audio", "Validate Exact Production Audio Hash")
    connect(connections, "Validate Exact Production Audio Hash", "Merge Production Binary + Verified Hash", 1)
    tail = [n["name"] for n in nodes[nodes.index(next(n for n in nodes if n["id"] == "merge_audio")):]]
    for source, target in zip(tail, tail[1:]):
        connect(connections, source, target)

    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True, "binaryMode": "separate"}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger"):
        if forbidden in raw:
            raise ValueError(f"production workflow contains forbidden value: {forbidden}")
    if workflow["active"]:
        raise ValueError("manual production workflow must import inactive")
    if "portable staging context" in raw:
        raise ValueError("production workflow contains a staging-context expression")
    if not any(n["type"] == "n8n-nodes-base.supabase" and n["parameters"].get("operation") == "create" for n in workflow["nodes"]):
        raise ValueError("native Supabase production create node missing")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
