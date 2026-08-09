#!/usr/bin/env python3
"""Build the visible post-GitHub completion verifier for episode 123 repair."""

from __future__ import annotations

import json
from pathlib import Path

from build_friday_audio_repair_20260809 import CLOUDINARY_CREDENTIAL, GITHUB_NATIVE_CREDENTIAL, code_node, connect, node


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-episode-123-repair-completion-2026-08-09.json"
SUPABASE = {"supabaseApi": {"id": "duPN6Njb1go7DN8w", "name": "Supabase (podcast)"}}


def build() -> dict:
    context = {
        "date": "2026-08-06",
        "episode": 123,
        "oldAudioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786010527/anitguru/gurus-tech-bytes-2026-08-06.mp3",
        "newAudioUrl": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786294036/anitguru/gurus-tech-bytes-2026-08-06-rerender-v2.mp3",
        "cloudinaryAssetId": "96ac23acfb82c41d950d4baa76e4105b",
        "githubPath": "content/podcast/2026-08-06.md",
        "githubCommitSha": "baafc7ce0dfaf726e31eb4289ae34ffcaba4296f",
        "audioBytes": 922605,
        "durationSeconds": 115.296,
        "audio_sha256": "8ef65833af25a95f64bc28993f57a6d29746ea7314cbde0626d3c7215875d8e5",
        "srt_sha256": "ecc04bd74a434363a4c3af96a3393a68f01bc1a396f8f124765a93d87de8b912",
        "alignment": {"wordErrorRate": 0.126722, "exactAnchorRatio": 0.936639, "cueCount": 26},
    }
    filters = {"filterType": "manual", "matchType": "allFilters", "filters": {"conditions": [
        {"keyName": "date", "condition": "eq", "keyValue": "={{ $('Episode 123 Completion Context').first().json.date }}"},
        {"keyName": "episode", "condition": "eq", "keyValue": "={{ $('Episode 123 Completion Context').first().json.episode }}"},
    ]}}
    nodes = [
        node("webhook", "Published Episode 123 Completion Webhook", "n8n-nodes-base.webhook", 0, {"httpMethod": "POST", "path": "podcast-episode-123-repair-completion-20260809", "responseMode": "onReceived", "options": {}}, typeVersion=2.1),
        code_node("context", "Episode 123 Completion Context", 240, "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];"),
        node("github", "GitHub - Read Back Episode 123 Corrected File", "n8n-nodes-base.github", 480, {"resource": "file", "operation": "get", "owner": {"mode": "name", "value": "anitguru"}, "repository": {"mode": "name", "value": "anit.guru"}, "filePath": "={{ $('Episode 123 Completion Context').first().json.githubPath }}", "asBinaryProperty": False, "additionalParameters": {"reference": "main"}}, typeVersion=1.1, credentials=GITHUB_NATIVE_CREDENTIAL),
        code_node("github_gate", "Validate Episode 123 Corrected GitHub File", 720, r"""const f=$input.first().json,c=$('Episode 123 Completion Context').first().json,raw=Buffer.from(String(f.content||'').replace(/\n/g,''),'base64').toString('utf8');
if(f.path!==c.githubPath||!raw.includes(c.newAudioUrl)||!raw.includes('episode one hundred twenty three.')||!raw.includes('episode: 123'))throw new Error('episode 123 corrected GitHub file mismatch');return [{json:{verified:true,contentSha:f.sha}}];"""),
        node("cloudinary", "Cloudinary - Read Back Episode 123 Corrected Audio", "n8n-nodes-cloudinary.cloudinary", 960, {"resource": "asset", "operation": "getAsset", "assetId": "={{ $('Episode 123 Completion Context').first().json.cloudinaryAssetId }}"}, typeVersion=2, credentials=CLOUDINARY_CREDENTIAL),
        code_node("cloud_gate", "Validate Episode 123 Corrected Cloudinary Asset", 1200, r"""const r=$input.first().json,c=$('Episode 123 Completion Context').first().json;
if(r.asset_id!==c.cloudinaryAssetId||r.secure_url!==c.newAudioUrl||Number(r.bytes)!==c.audioBytes||r.placeholder===true)throw new Error('episode 123 Cloudinary readback mismatch');return [{json:{verified:true,assetId:r.asset_id,url:r.secure_url,bytes:r.bytes}}];"""),
        node("supabase_get", "Supabase - Read Episode 123 Before Completion", "n8n-nodes-base.supabase", 1440, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE),
        code_node("prepare", "Prepare Episode 123 Supabase Completion", 1680, r"""const r=$input.first().json,c=$('Episode 123 Completion Context').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==c.oldAudioUrl||!Array.isArray(r.stories)||r.stories.length!==4)throw new Error('episode 123 Supabase source changed');return [{json:{date:r.date,episode:r.episode,stories:r.stories,audio_url:c.newAudioUrl,duration_secs:Math.round(c.durationSeconds)}}];"""),
        node("supabase_update", "Supabase - Complete Episode 123 Audio Replacement", "n8n-nodes-base.supabase", 1920, {"resource": "row", "operation": "update", "tableId": "podcast_episodes", "dataToSend": "autoMapInputData", "inputsToIgnore": "", **filters}, typeVersion=1, credentials=SUPABASE),
        node("supabase_read", "Supabase - Read Back Episode 123 Completion", "n8n-nodes-base.supabase", 2160, {"resource": "row", "operation": "getAll", "tableId": "podcast_episodes", "returnAll": False, "limit": 1, "orderBy": "episode.desc", **filters}, typeVersion=1, credentials=SUPABASE),
        code_node("gate", "Hard Episode 123 Completion Gate", 2400, r"""const r=$input.first().json,c=$('Episode 123 Completion Context').first().json,g=$('Validate Episode 123 Corrected GitHub File').first().json,u=$('Validate Episode 123 Corrected Cloudinary Asset').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==c.newAudioUrl||Number(r.duration_secs)!==Math.round(c.durationSeconds)||g.verified!==true||u.verified!==true)throw new Error('episode 123 completion proof failed');return [{json:{repairValidated:true,...c,github:g,cloudinary:u,supabase:r}}];"""),
        node("ledger", "Ledger - Episode 123 Audio + Timestamp Repair Complete", "n8n-nodes-base.dataTable", 2640, {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "audio-timestamp-repair/2026-08-06/123", "execution_id": "={{ $execution.id }}", "run_mode": "production-repair", "episode": 123, "episode_date": "2026-08-06", "stage": "audio-timestamp-link-replaced", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($json.supabase.stories) }}", "script_sha256": "ca601d6d32ef3c9807207442ec5678f26c373e826eb2ebe5913ca6c97b9b3db0", "audio_sha256": "={{ $json.audio_sha256 }}", "srt_sha256": "={{ $json.srt_sha256 }}", "qa_json": "={{ JSON.stringify({durationSeconds:$json.durationSeconds,alignment:$json.alignment}) }}", "artifact_urls_json": "={{ JSON.stringify({audio:$json.newAudioUrl,github:$json.github,cloudinary:$json.cloudinary}) }}", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1),
        code_node("return", "Return Episode 123 Completion Proof", 2880, "return [{json:$('Hard Episode 123 Completion Gate').first().json}];"),
    ]
    connections = {}
    for source, target in zip((item["name"] for item in nodes), (item["name"] for item in nodes[1:])):
        connect(connections, source, target)
    workflow = {"id": "pEpisode123CompleteX8", "name": "WF-podcast-episode-123-repair-completion-2026-08-09", "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    raw = json.dumps(workflow).lower()
    if len(nodes) != 13 or "scheduletrigger" in raw or "ssh" in raw or "httprequest" in raw:
        raise ValueError("episode 123 completion architecture guard failed")
    return workflow


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(OUTPUT)
