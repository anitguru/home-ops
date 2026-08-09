#!/usr/bin/env python3
"""Build a visible, text-only regression for TTS provenance persistence/Telegram."""

from __future__ import annotations

import json
from pathlib import Path

from build_portable_staging_v1 import TELEGRAM_CREDENTIAL, code_node, node


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-tts-provenance-regression-2026-08-09.json"


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    nodes = [
        node("webhook", "Published TTS Provenance Regression Webhook", "n8n-nodes-base.webhook", 0, {"httpMethod": "POST", "path": "podcast-tts-provenance-regression-20260809", "responseMode": "onReceived", "options": {}}, typeVersion=2.1),
        code_node("context", "Frozen LXC TTS Provenance", 240, "return [{json:{runId:'tts-provenance-regression/2026-08-09/1',date:'2026-08-09',episode:126,ttsProcessor:'lxc-137-cpu',ttsProcessorLabel:'LXC 137 (CPU)',ttsEndpointHost:'chatterbox.transformers.lan',ttsProfile:'chatterbox-turbo-ct137-visible-v1'}}];"),
        code_node("notification", "Prepare Provenance Telegram Confirmation", 480, r"""const c=$input.first().json;
return [{json:{...c,text:`🧪 TTS provenance regression — EP #${c.episode}\n🗣️ TTS processor: ${c.ttsProcessorLabel}\nProfile: ${c.ttsProfile}`}}];"""),
        node("telegram", "Telegram - Send Provenance Confirmation", "n8n-nodes-base.telegram", 720, {"resource": "message", "operation": "sendMessage", "chatId": "8100669692", "text": "={{ $json.text }}", "additionalFields": {"disable_notification": True}}, typeVersion=1.2, credentials=TELEGRAM_CREDENTIAL),
        code_node("gate", "Validate Telegram + Provenance Contract", 960, r"""const sent=$input.first().json,c=$('Prepare Provenance Telegram Confirmation').first().json,id=sent.result?.message_id;
if(!Number.isInteger(id)||id<1)throw new Error('Telegram provenance confirmation missing');
if(c.ttsProcessor!=='lxc-137-cpu'||c.ttsProcessorLabel!=='LXC 137 (CPU)'||!c.text.includes('TTS processor: LXC 137 (CPU)')||!c.text.includes(c.ttsProfile))throw new Error('TTS provenance contract invalid');
return [{json:{...c,telegramMessageId:id,validated:true}}];"""),
        node("ledger", "Ledger - TTS Provenance Regression Passed", "n8n-nodes-base.dataTable", 1200, {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "={{ $json.runId }}", "execution_id": "={{ $execution.id }}", "run_mode": "regression", "episode": "={{ $json.episode }}", "episode_date": "={{ $json.date }}", "stage": "tts-provenance-regression", "status": "passed", "attempt": 1, "selected_stories_json": "", "script_sha256": "", "audio_sha256": "", "srt_sha256": "", "tts_processor": "={{ $json.ttsProcessor }}", "tts_endpoint_host": "={{ $json.ttsEndpointHost }}", "tts_profile": "={{ $json.ttsProfile }}", "qa_json": "={{ JSON.stringify({tts:{processor:$json.ttsProcessor,label:$json.ttsProcessorLabel,endpointHost:$json.ttsEndpointHost,profile:$json.ttsProfile},telegramMessageId:$json.telegramMessageId}) }}", "artifact_urls_json": "", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1),
        code_node("return", "Return TTS Provenance Regression Proof", 1440, "return [{json:$('Validate Telegram + Provenance Contract').first().json}];"),
    ]
    connections = {}
    for source, target in zip((item["name"] for item in nodes), (item["name"] for item in nodes[1:])):
        connect(connections, source, target)
    workflow = {"id": "pTtsProvRegX8Q3M7", "name": "WF-podcast-tts-provenance-regression-2026-08-09", "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    raw = json.dumps(workflow).lower()
    if len(nodes) != 7 or "scheduletrigger" in raw or "ssh" in raw or "chatterbox - render" in raw:
        raise ValueError("TTS provenance regression must remain text-only and unscheduled")
    return workflow


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(OUTPUT)
