#!/usr/bin/env python3
"""Build the portable podcast media-render sub-workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-sub-media-v1.json"
WORKFLOW_ID = "pMediaSubX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-media-v1"
VOICE_BASE = "https://chatterbox.transformers.lan/v1/audio"


def node(node_id: str, name: str, node_type: str, x: int, y: int, parameters: dict, **extra: object) -> dict:
    result = {"id": node_id, "name": name, "type": node_type, "typeVersion": extra.pop("typeVersion", 1), "position": [x, y], "parameters": parameters}
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, y: int, js: str, notes: str = "") -> dict:
    return node(node_id, name, "n8n-nodes-base.code", x, y, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()}, typeVersion=2, notes=notes)


def http(node_id: str, name: str, x: int, y: int, parameters: dict, notes: str) -> dict:
    parameters.setdefault("options", {})["allowUnauthorizedCerts"] = True
    return node(node_id, name, "n8n-nodes-base.httpRequest", x, y, parameters, typeVersion=4.4, notes=f"HTTP exception: {notes}")


def connect(connections: dict, source: str, target: str, target_input: int = 0) -> None:
    connections.setdefault(source, {"main": [[]]})["main"][0].append({"node": target, "type": "main", "index": target_input})


def tts_node(index: int, x: int) -> dict:
    number = f"{index:02d}"
    return http(
        f"tts_{number}",
        f"Chatterbox - Render Segment {number}",
        x,
        0,
        {
            "method": "POST",
            "url": f"{VOICE_BASE}/speech",
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": "={{ {model:'tts-1',input:$json.segments[" + str(index - 1) + "],voice:'peter-griffin.wav',response_format:'mp3',speed:1,seed:0} }}",
            "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": f"segment{number}"}}, "timeout": 900000},
        },
        "Chatterbox has no native n8n node; this node renders exactly one visible paragraph through the voice-service API.",
    )


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    manual = {"runMode": "shadow", "date": fixture["date"], "runId": "media-fixture/run37", "episode": fixture["episode"], "selectedStories": fixture["selectedStories"], "scriptText": fixture["scriptText"], "script_sha256": hashlib.sha256(fixture["scriptText"].encode()).hexdigest()}
    nodes = [
        node("manual", "Manual Media Test Trigger", "n8n-nodes-base.manualTrigger", 0, -180, {}),
        node("sub_trigger", "When Called by Parent Workflow", "n8n-nodes-base.executeWorkflowTrigger", 0, 80, {"inputSource": "jsonExample", "jsonExample": json.dumps({"runMode": "shadow", "date": "2026-08-08", "runId": "portable-shadow/example", "episode": 125, "selectedStories": [], "scriptText": "six paragraphs", "script_sha256": "0" * 64}, indent=2)}, typeVersion=1.2),
        code("fixture", "Prepare Media Fixture", 240, -180, "return [{json:" + json.dumps(manual, separators=(",", ":")) + "}];"),
        code(
            "segments",
            "Prepare Six TTS Segments",
            480,
            0,
            r"""const r=$input.first().json;
if(!['shadow','production'].includes(r.runMode)) throw new Error('media requires shadow or production mode');
if(!/^[a-f0-9]{64}$/.test(String(r.script_sha256||''))) throw new Error('approved script hash missing');
const segments=String(r.scriptText||'').split(/\n\s*\n/).map(x=>x.trim()).filter(Boolean);
if(segments.length!==6||segments.some(x=>x.length<10)) throw new Error('media requires six non-empty paragraphs');
return [{json:{...r,segments,ttsProcessor:'lxc-137-cpu',ttsProcessorLabel:'LXC 137 (CPU)',ttsEndpointHost:'chatterbox.transformers.lan',ttsProfile:'chatterbox-turbo-ct137-visible-v1'}}];""",
        ),
        *[tts_node(index, 480 + index * 240) for index in range(1, 7)],
        http(
            "assemble",
            "Chatterbox - Assemble Six Segments",
            2160,
            0,
            {
                "method": "POST",
                "url": f"{VOICE_BASE}/assemble-six",
                "sendBody": True,
                "contentType": "multipart-form-data",
                "bodyParameters": {"parameters": [
                    {"parameterType": "formBinaryData", "name": f"segment{index:02d}", "inputDataFieldName": f"segment{index:02d}"}
                    for index in range(1, 7)
                ]},
                "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "audio"}}, "timeout": 300000},
            },
            "n8n has no native audio decode/concatenate/loudness-normalize node; the versioned stateless voice route performs only that operation.",
        ),
        node("hash", "SHA256 Assembled Audio", "n8n-nodes-base.crypto", 2400, -140, {"action": "hash", "binaryData": True, "binaryPropertyName": "audio", "type": "SHA256", "dataPropertyName": "audio_sha256", "encoding": "hex"}, typeVersion=2),
        http(
            "qa",
            "Chatterbox - Objective Audio QA",
            2400,
            140,
            {"method": "POST", "url": f"{VOICE_BASE}/objective-qa", "sendBody": True, "contentType": "multipart-form-data", "bodyParameters": {"parameters": [{"parameterType": "formBinaryData", "name": "audio", "inputDataFieldName": "audio"}]}, "options": {"timeout": 300000}},
            "n8n has no native LUFS/true-peak/clipping/long-silence analyzer; the versioned stateless voice route returns objective metrics only.",
        ),
        node("merge_qa", "Merge Audio Hash + QA Metrics", "n8n-nodes-base.merge", 2640, 0, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        code(
            "gate",
            "Hard Objective Audio Quality Gate",
            2880,
            0,
            r"""const r=$input.first().json;const failures=[];
if(!/^[a-f0-9]{64}$/.test(String(r.audio_sha256||''))) failures.push('hash');
if(Number(r.duration_seconds)<60) failures.push('duration');
if(Number(r.integrated_lufs)<-18||Number(r.integrated_lufs)>-14) failures.push('loudness');
if(Number(r.true_peak_dbtp)>-1.5) failures.push('true peak');
if(Number(r.clipped_samples)!==0) failures.push('clipping');
if(Number(r.long_silence_ratio)>0.08) failures.push('silence');
if(failures.length) throw new Error(`objective audio gate: ${failures.join(', ')}`);
const context=$('Prepare Six TTS Segments').first().json;
return [{json:{...context,audio_sha256:r.audio_sha256,audioQa:{duration_seconds:r.duration_seconds,integrated_lufs:r.integrated_lufs,true_peak_dbtp:r.true_peak_dbtp,clipped_samples:r.clipped_samples,long_silence_ratio:r.long_silence_ratio,sample_rate_hz:r.sample_rate_hz,channels:r.channels},mediaValidated:true}}];""",
        ),
        node(
            "ledger",
            "Ledger - Media QA Passed",
            "n8n-nodes-base.dataTable",
            3120,
            0,
            {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "={{ $json.runId }}", "execution_id": "={{ $execution.id }}", "run_mode": "shadow", "episode": "={{ $json.episode }}", "episode_date": "={{ $json.date }}", "stage": "media-qa", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($json.selectedStories) }}", "script_sha256": "={{ $json.script_sha256 }}", "audio_sha256": "={{ $json.audio_sha256 }}", "srt_sha256": "", "tts_processor": "={{ $json.ttsProcessor }}", "tts_endpoint_host": "={{ $json.ttsEndpointHost }}", "tts_profile": "={{ $json.ttsProfile }}", "qa_json": "={{ JSON.stringify({audio:$json.audioQa,tts:{processor:$json.ttsProcessor,label:$json.ttsProcessorLabel,endpointHost:$json.ttsEndpointHost,profile:$json.ttsProfile}}) }}", "artifact_urls_json": "", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}},
            typeVersion=1.1,
        ),
        node("merge_contract", "Merge Audio Binary + Media Contract", "n8n-nodes-base.merge", 3360, 0, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        code(
            "return_contract",
            "Return Clean Media Contract",
            3600,
            0,
            r"""const r=$input.first();const qa=JSON.parse(r.json.qa_json||'{}');
if(!r.binary?.audio) throw new Error('assembled audio binary missing at media boundary');
return [{json:{runMode:r.json.runMode,date:r.json.date,runId:r.json.runId,episode:r.json.episode,selectedStories:r.json.selectedStories,scriptText:r.json.scriptText,script_sha256:r.json.script_sha256,audio_sha256:r.json.audio_sha256,audioQa:qa,mediaValidated:true,ttsProcessor:r.json.ttsProcessor,ttsProcessorLabel:r.json.ttsProcessorLabel,ttsEndpointHost:r.json.ttsEndpointHost,ttsProfile:r.json.ttsProfile},binary:{audio:r.binary.audio}}];""",
            notes="Reusable boundary returns one assembled audio binary and the explicit validated contract; temporary segment binaries do not leave this workflow.",
        ),
    ]

    connections: dict = {}
    connect(connections, "Manual Media Test Trigger", "Prepare Media Fixture")
    connect(connections, "Prepare Media Fixture", "Prepare Six TTS Segments")
    connect(connections, "When Called by Parent Workflow", "Prepare Six TTS Segments")
    chain = ["Prepare Six TTS Segments"] + [f"Chatterbox - Render Segment {index:02d}" for index in range(1, 7)] + ["Chatterbox - Assemble Six Segments"]
    for source, target in zip(chain, chain[1:]):
        connect(connections, source, target)
    connect(connections, "Chatterbox - Assemble Six Segments", "SHA256 Assembled Audio")
    connect(connections, "Chatterbox - Assemble Six Segments", "Chatterbox - Objective Audio QA")
    connect(connections, "Chatterbox - Assemble Six Segments", "Merge Audio Binary + Media Contract", 0)
    connect(connections, "SHA256 Assembled Audio", "Merge Audio Hash + QA Metrics", 0)
    connect(connections, "Chatterbox - Objective Audio QA", "Merge Audio Hash + QA Metrics", 1)
    connect(connections, "Merge Audio Hash + QA Metrics", "Hard Objective Audio Quality Gate")
    connect(connections, "Hard Objective Audio Quality Gate", "Ledger - Media QA Passed")
    connect(connections, "Ledger - Media QA Passed", "Merge Audio Binary + Media Contract", 1)
    connect(connections, "Merge Audio Binary + Media Contract", "Return Clean Media Contract")

    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True, "binaryMode": "separate"}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh"):
        if forbidden in raw:
            raise ValueError(f"media workflow contains forbidden value: {forbidden}")
    http_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    if len(http_nodes) != 8:
        raise ValueError("media workflow must expose six TTS, one assembly, and one QA HTTP node")
    if any(not n.get("notes", "").startswith("HTTP exception:") for n in http_nodes):
        raise ValueError("every media HTTP node must document its built-in-node exception")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            lines = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(lines) > 20:
                raise ValueError(f"media Code node too large: {item['name']} ({len(lines)} lines)")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
