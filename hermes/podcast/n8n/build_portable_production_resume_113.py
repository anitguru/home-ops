#!/usr/bin/env python3
"""Build a visible one-shot completion workflow for partial production execution 113."""

from __future__ import annotations

import json
from pathlib import Path

from build_portable_staging_v1 import GITHUB_NATIVE_CREDENTIAL, TELEGRAM_CREDENTIAL, code_node, ledger_node as staging_ledger_node, node
from build_portable_production_v1 import SUPABASE_CREDENTIAL


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-portable-production-resume-113.json"
WORKFLOW_ID = "pProdResume113X8Q3"
WORKFLOW_NAME = "WF-podcast-portable-production-resume-113"


def ledger_node(node_id: str, name: str, x: int, stage: str, status: str, **fields: str) -> dict:
    result = staging_ledger_node(node_id, name, x, stage, status, **fields)
    values = result["parameters"]["columns"]["value"]
    for key, value in values.items():
        if isinstance(value, str):
            values[key] = value.replace("Portable Staging Context", "Production Resume 113 Context").replace(".json.portableRunId", ".json.runId")
    values["run_mode"] = "production-recovery"
    values["srt_sha256"] = fields.get("srt_sha256", "")
    return result


def connect(connections: dict, source: str, target: str, target_input: int = 0) -> None:
    connections.setdefault(source, {"main": [[]]})["main"][0].append({"node": target, "type": "main", "index": target_input})


def build() -> dict:
    stories = [
        {"id": "49209539", "title": "What happens if an entire class of workers loses faith in their careers", "url": "https://www.noemamag.com/why-is-everyone-in-tech-so-sad/", "hnUrl": "https://news.ycombinator.com/item?id=49209539", "score": 964},
        {"id": "49214008", "title": "DeepSeek V4 Flash 0731", "url": "https://arcprize.org/results/deepseek-v4-flash-0731", "hnUrl": "https://news.ycombinator.com/item?id=49214008", "score": 754},
        {"id": "49220126", "title": "DeepMind's WeatherNext model achieves breakthrough forecasting cyclones", "url": "https://deepmind.google/blog/weathernext-ai-model-achieves-breakthrough-in-forecasting-cyclones/", "hnUrl": "https://news.ycombinator.com/item?id=49220126", "score": 352},
        {"id": "49219508", "title": "Hardware backdoors in some x86 CPUs", "url": "https://github.com/xoreaxeaxeax/rosenbridge", "hnUrl": "https://news.ycombinator.com/item?id=49219508", "score": 322},
    ]
    context = {
        "runMode": "shadow", "publishMode": "production-recovery", "manualProductionApproved": True,
        "date": "2026-08-08", "runId": "portable-production/2026-08-08/113", "episode": 125,
        "selectedStories": stories, "script_sha256": "6fe6b77a6fc9901b1fa491b79e7ae03941df16abf737e9fa93f548f0b3975261",
        "audio_sha256": "f2b9cea5af9c54d460d286eb60fb53b808e0c41caf30c61c732103c0fe553814",
        "audioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786230258/anitguru/gurus-tech-bytes-2026-08-08.mp3",
        "audioQa": {"duration_seconds": 125.808, "integrated_lufs": -17.3, "true_peak_dbtp": -1.7, "clipped_samples": 0, "long_silence_ratio": 0, "sample_rate_hz": 24000, "channels": 1},
        "githubPath": "content/podcast/2026-08-08.md", "githubCommit": "c2f88c1f7ac7651693eef9b2eb207930c24b71c4",
    }
    filters = {"filterType": "manual", "matchType": "allFilters", "filters": {"conditions": [{"keyName": "date", "condition": "eq", "keyValue": "={{ $('Production Resume 113 Context').first().json.date }}"}]}}
    nodes = [
        node("manual", "Manual Resume Production 113 Trigger", "n8n-nodes-base.manualTrigger", 0, {}),
        code_node("context", "Production Resume 113 Context", 240, "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];", "Pinned nonsecret proof from failed-closed execution 113; it can repair only this exact date, episode, hashes, URL, and commit."),
        code_node("gate", "Hard Production Resume 113 Gate", 480, r"""const c=$input.first().json;if(c.manualProductionApproved!==true||c.date!=='2026-08-08'||c.episode!==125||c.githubCommit!=='c2f88c1f7ac7651693eef9b2eb207930c24b71c4'||c.audio_sha256!=='f2b9cea5af9c54d460d286eb60fb53b808e0c41caf30c61c732103c0fe553814')throw new Error('production resume target mismatch');return [{json:c}];"""),
        node("github_get", "GitHub - Re-read Production Episode", "n8n-nodes-base.github", 720, {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $json.githubPath }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}}, typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL),
        code_node("parse_page", "Validate Page + Recover Approved Transcript", 960, r"""const f=$input.first().json,c=$('Production Resume 113 Context').first().json,raw=Buffer.from(String(f.content||'').replace(/\n/g,''),'base64').toString('utf8');const parts=raw.split(/^---\s*$/m);const scriptText=(parts[2]||'').trim();if(f.path!==c.githubPath||!raw.includes(`episode: ${c.episode}`)||!raw.includes(c.audioUrl)||scriptText.split(/\n\n/).length!==6)throw new Error('production page/transcript readback invalid');return [{json:{...c,scriptText,mediaValidated:true}}];"""),
        node("head_audio", "HEAD Re-verify Production MP3", "n8n-nodes-base.httpRequest", 1200, {"method": "HEAD", "url": "={{ $json.audioUrl }}", "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}}, "timeout": 20000}}, typeVersion=4.4, notes="HTTP exception: the Cloudinary community node has no delivery-URL HEAD action."),
        code_node("head_gate", "Gate - Production MP3 Reachable", 1440, r"""const r=$input.first().json,c=$('Validate Page + Recover Approved Transcript').first().json;if(Number(r.statusCode)<200||Number(r.statusCode)>=400)throw new Error(`production MP3 HEAD ${r.statusCode}`);return [{json:c}];"""),
        node("download_audio", "Download Exact Production MP3", "n8n-nodes-base.httpRequest", 1680, {"url": "={{ $json.audioUrl }}", "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "audio"}}, "timeout": 120000}}, typeVersion=4.4, notes="HTTP exception: the Cloudinary community node has no binary download action."),
        node("hash_audio", "SHA256 Recovered Production MP3", "n8n-nodes-base.crypto", 1920, {"action": "hash", "binaryData": True, "binaryPropertyName": "audio", "type": "SHA256", "dataPropertyName": "audio_sha256", "encoding": "hex"}, typeVersion=2),
        code_node("hash_gate", "Gate - Exact Production MP3 Hash", 2160, r"""const r=$input.first().json,c=$('Validate Page + Recover Approved Transcript').first().json;if(r.audio_sha256!==c.audio_sha256)throw new Error('recovered production MP3 hash mismatch');return [{json:c}];"""),
        node("merge_audio", "Merge Recovered MP3 + Proven Context", "n8n-nodes-base.merge", 2400, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        node("call_transcription", "Run Reusable Transcription + SRT", "n8n-nodes-base.executeWorkflow", 2640, {"source": "database", "workflowId": {"__rl": True, "value": "pTransSubX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-sub-transcription-v1"}, "workflowInputs": {"mappingMode": "defineBelow", "value": {field: f"={{{{ $json.{field} }}}}" for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "mediaValidated")}, "matchingColumns": [], "schema": [{"id": field, "displayName": field, "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number" if field == "episode" else "array" if field == "selectedStories" else "object" if field == "audioQa" else "boolean" if field == "mediaValidated" else "string"} for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "mediaValidated")], "attemptToConvertTypes": False, "convertFieldsToString": False}, "mode": "once", "options": {"waitForSubWorkflow": True}}, typeVersion=1.3),
        code_node("validate_transcription", "Validate Recovered Production SRT", 2880, r"""const i=$input.first(),r=i.json,a=r.alignment||{};if(r.transcriptionValidated!==true||!i.binary?.audio||!i.binary?.srt||a.wordErrorRate>0.20||a.maximumLineCharacters>47||a.maximumLinesPerCue>2)throw new Error('recovered production SRT proof invalid');return [i];"""),
        code_node("prepare_row", "Prepare Correct Native Supabase Row", 3120, r"""const r=$input.first().json;return [{json:{date:r.date,episode:r.episode,stories:r.selectedStories,audio_url:$('Production Resume 113 Context').first().json.audioUrl,duration_secs:Math.round(r.audioQa.duration_seconds)}}];"""),
        node("supabase_update", "Supabase - Correct Production Episode 125", "n8n-nodes-base.supabase", 3360, {"resource": "row", "operation": "update", "tableId": "podcast_episodes", "dataToSend": "autoMapInputData", "inputsToIgnore": "", **filters}, typeVersion=1, credentials=SUPABASE_CREDENTIAL),
        node("supabase_get", "Supabase - Verify Correct Production Row", "n8n-nodes-base.supabase", 3600, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE_CREDENTIAL),
        code_node("validate_row", "Validate Correct Supabase Types + Values", 3840, r"""const r=$input.first().json,c=$('Production Resume 113 Context').first().json;if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==c.audioUrl||!Array.isArray(r.stories)||r.stories.length!==4||Number(r.duration_secs)!==126)throw new Error('corrected Supabase row invalid');return [{json:{row:r,verified:true}}];"""),
        ledger_node("ledger_db", "Ledger - Production Row Repaired", 4080, "production-database-repaired", "passed", audio_sha256="={{ $('Production Resume 113 Context').first().json.audio_sha256 }}", srt_sha256="={{ $('Validate Recovered Production SRT').first().json.srt_sha256 }}", artifact_urls_json="={{ JSON.stringify({audio:$('Production Resume 113 Context').first().json.audioUrl,github:$('Production Resume 113 Context').first().json.githubCommit}) }}"),
        code_node("notify_text", "Prepare Recovered Production Notification", 4320, r"""const c=$('Production Resume 113 Context').first().json;return [{json:{text:`🎙️ Guru's Tech Bytes EP #${c.episode} is live — ${c.date}\n${c.audioUrl}`}}];"""),
        node("telegram_text", "Telegram - Send Production Summary", "n8n-nodes-base.telegram", 4560, {"resource": "message", "operation": "sendMessage", "chatId": "8100669692", "text": "={{ $json.text }}", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("restore_audio", "Restore Production MP3 for Telegram", 4800, r"""const i=$('Validate Recovered Production SRT').first();return [{json:{},binary:{audio:i.binary.audio}}];"""),
        node("telegram_audio", "Telegram - Send Production MP3", "n8n-nodes-base.telegram", 5040, {"resource": "message", "operation": "sendAudio", "chatId": "8100669692", "binaryData": True, "binaryPropertyName": "audio", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("restore_srt", "Restore Production SRT for Telegram", 5280, r"""const i=$('Validate Recovered Production SRT').first();return [{json:{},binary:{srt:i.binary.srt}}];"""),
        node("telegram_srt", "Telegram - Send Production SRT", "n8n-nodes-base.telegram", 5520, {"resource": "message", "operation": "sendDocument", "chatId": "8100669692", "binaryData": True, "binaryPropertyName": "srt", "additionalFields": {}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("validate_delivery", "Validate Three Production Telegram Messages", 5760, r"""const ids=[$('Telegram - Send Production Summary').first().json.result?.message_id,$('Telegram - Send Production MP3').first().json.result?.message_id,$input.first().json.result?.message_id];if(ids.some(x=>!Number.isInteger(x)||x<1))throw new Error('production Telegram delivery incomplete');return [{json:{messageIds:ids,verified:true}}];"""),
        ledger_node("ledger_complete", "Ledger - Production 113 Completed", 6000, "production-complete", "passed", audio_sha256="={{ $('Production Resume 113 Context').first().json.audio_sha256 }}", srt_sha256="={{ $('Validate Recovered Production SRT').first().json.srt_sha256 }}", qa_json="={{ JSON.stringify($('Validate Recovered Production SRT').first().json.alignment) }}", artifact_urls_json="={{ JSON.stringify({audio:$('Production Resume 113 Context').first().json.audioUrl,github:$('Production Resume 113 Context').first().json.githubCommit,telegram:$('Validate Three Production Telegram Messages').first().json.messageIds}) }}"),
        code_node("return_contract", "Return Recovered Production Contract", 6240, r"""const c=$('Production Resume 113 Context').first().json,t=$('Validate Recovered Production SRT').first().json,n=$('Validate Three Production Telegram Messages').first().json;return [{json:{date:c.date,episode:c.episode,audioUrl:c.audioUrl,audio_sha256:c.audio_sha256,srt_sha256:t.srt_sha256,alignment:t.alignment,githubCommit:c.githubCommit,supabasePersisted:true,telegramMessageIds:n.messageIds,productionValidated:true}}];"""),
    ]
    connections: dict = {}
    first = [n["name"] for n in nodes[:8]]
    for source, target in zip(first, first[1:]): connect(connections, source, target)
    connections["Download Exact Production MP3"] = {"main": [[{"node": "SHA256 Recovered Production MP3", "type": "main", "index": 0}, {"node": "Merge Recovered MP3 + Proven Context", "type": "main", "index": 0}]]}
    connect(connections, "SHA256 Recovered Production MP3", "Gate - Exact Production MP3 Hash")
    connect(connections, "Gate - Exact Production MP3 Hash", "Merge Recovered MP3 + Proven Context", 1)
    tail = [n["name"] for n in nodes[nodes.index(next(n for n in nodes if n["id"] == "merge_audio")):]]
    for source, target in zip(tail, tail[1:]): connect(connections, source, target)
    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": False, "binaryMode": "separate"}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger", "portable staging context"):
        if forbidden in raw: raise ValueError(f"resume workflow contains forbidden value: {forbidden}")
    if workflow["active"]: raise ValueError("resume workflow must import inactive")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
