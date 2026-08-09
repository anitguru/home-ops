#!/usr/bin/env python3
"""Build the portable parent podcast workflow.

The parent is deliberately thin. Each major stage is a first-class Execute
Sub-workflow node so the canvas shows orchestration while the child canvas
shows the reusable implementation.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-portable-shadow-v1.json"
WORKFLOW_ID = "pPortableShX8Q3M7"
WORKFLOW_NAME = "WF-podcast-portable-shadow-v1"


def node(node_id: str, name: str, node_type: str, x: int, parameters: dict, **extra: object) -> dict:
    result = {
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": extra.pop("typeVersion", 1),
        "position": [x, 0],
        "parameters": parameters,
    }
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, js: str, notes: str = "") -> dict:
    return node(
        node_id,
        name,
        "n8n-nodes-base.code",
        x,
        {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()},
        typeVersion=2,
        notes=notes,
    )


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    nodes = [
        node("manual", "Manual Portable Shadow Trigger", "n8n-nodes-base.manualTrigger", 0, {}),
        code(
            "context",
            "Prepare Portable Shadow Context",
            260,
            r"""const now=new Date();
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
return [{json:{runMode:'shadow',publishMode:'staging',notifyMode:'test-summary',date,runId:`portable-shadow/${date}/${$execution.id}`,attempt:1}}];""",
        ),
        code(
            "gate",
            "Portable Shadow Safety Gate",
            520,
            r"""const c=$input.first().json;
const failures=[];
if(c.runMode!=='shadow') failures.push('runMode');
if(c.publishMode!=='staging') failures.push('publishMode');
if(c.notifyMode!=='test-summary') failures.push('notifyMode');
if(!/^portable-shadow\/\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]+$/.test(c.runId)) failures.push('runId');
if(failures.length) throw new Error(`portable safety gate: ${failures.join(', ')}`);
return [{json:c}];""",
        ),
        node(
            "ledger_start",
            "Ledger - Portable Run Started",
            "n8n-nodes-base.dataTable",
            780,
            {
                "resource": "row",
                "operation": "insert",
                "dataTableId": {"mode": "name", "value": "podcast_run_ledger"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "run_id": "={{ $json.runId }}",
                        "execution_id": "={{ $execution.id }}",
                        "run_mode": "shadow",
                        "episode": 0,
                        "episode_date": "={{ $json.date }}",
                        "stage": "portable-start",
                        "status": "running",
                        "attempt": 1,
                        "selected_stories_json": "",
                        "script_sha256": "",
                        "audio_sha256": "",
                        "srt_sha256": "",
                        "qa_json": "",
                        "artifact_urls_json": "",
                        "error": "",
                        "started_at": "={{ $now.toISO() }}",
                        "updated_at": "={{ $now.toISO() }}",
                    },
                },
                "options": {},
            },
            typeVersion=1.1,
        ),
        node(
            "call_intake",
            "Run Intake + Ranking Sub-workflow",
            "n8n-nodes-base.executeWorkflow",
            1040,
            {
                "source": "database",
                "workflowId": {
                    "__rl": True,
                    "value": "pIntakeSubX8Q3M7",
                    "mode": "list",
                    "cachedResultName": "WF-podcast-sub-intake-v1",
                },
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "runMode": "={{ $('Portable Shadow Safety Gate').first().json.runMode }}",
                        "date": "={{ $('Portable Shadow Safety Gate').first().json.date }}",
                        "runId": "={{ $('Portable Shadow Safety Gate').first().json.runId }}",
                        "attempt": "={{ $('Portable Shadow Safety Gate').first().json.attempt }}",
                    },
                    "matchingColumns": [],
                    "schema": [
                        {"id": "runMode", "displayName": "runMode", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "date", "displayName": "date", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "runId", "displayName": "runId", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "attempt", "displayName": "attempt", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
                    ],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": False,
                },
                "mode": "once",
                "options": {"waitForSubWorkflow": True},
            },
            typeVersion=1.3,
            notes="Calls the reusable native Supabase + Hacker News intake workflow and waits for its proven contract.",
        ),
        code(
            "validate_intake",
            "Validate Intake Sub-workflow Contract",
            1300,
            r"""const r=$input.first().json;
if(r.runMode!=='shadow'||!Number.isInteger(r.episode)||r.episode<1) throw new Error('invalid intake episode contract');
if(!Array.isArray(r.selectedStories)||r.selectedStories.length!==4) throw new Error('intake did not return four stories');
if(r.rankingProof?.domainDiverse!==true||r.rankingProof?.selectedCount!==4) throw new Error('ranking proof missing');
return [{json:r}];""",
        ),
        node(
            "call_authoring",
            "Run Authoring Sub-workflow",
            "n8n-nodes-base.executeWorkflow",
            1560,
            {
                "source": "database",
                "workflowId": {"__rl": True, "value": "pAuthorSubX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-sub-authoring-v1"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "runMode": "={{ $json.runMode }}",
                        "date": "={{ $json.date }}",
                        "runId": "={{ $json.runId }}",
                        "attempt": "={{ $json.attempt }}",
                        "episode": "={{ $json.episode }}",
                        "selectedStories": "={{ $json.selectedStories }}",
                    },
                    "matchingColumns": [],
                    "schema": [
                        {"id": "runMode", "displayName": "runMode", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "date", "displayName": "date", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "runId", "displayName": "runId", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                        {"id": "attempt", "displayName": "attempt", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
                        {"id": "episode", "displayName": "episode", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
                        {"id": "selectedStories", "displayName": "selectedStories", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "array"},
                    ],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": False,
                },
                "mode": "once",
                "options": {"waitForSubWorkflow": True},
            },
            typeVersion=1.3,
            notes="Calls native GLM-5.2 authoring with bounded retries and the reusable script-validator workflow.",
        ),
        code(
            "validate_authoring",
            "Validate Authoring Sub-workflow Contract",
            1820,
            r"""const r=$input.first().json;
if(r.authoringValidated!==true||![1,2,3].includes(r.authoringAttempt)) throw new Error('authoring validation proof missing');
if(r.paragraphCount!==6||r.wordCount<330||r.wordCount>400) throw new Error('authoring shape invalid');
if(!/^[a-f0-9]{64}$/.test(String(r.script_sha256||''))) throw new Error('script hash missing');
return [{json:r}];""",
        ),
        node(
            "call_media",
            "Run Media Render + QA Sub-workflow",
            "n8n-nodes-base.executeWorkflow",
            2080,
            {
                "source": "database",
                "workflowId": {"__rl": True, "value": "pMediaSubX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-sub-media-v1"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {field: "={{ Number($json.episode) }}" if field == "episode" else f"={{{{ $json.{field} }}}}" for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256")},
                    "matchingColumns": [],
                    "schema": [
                        {"id": field, "displayName": field, "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "array" if field == "selectedStories" else "number" if field == "episode" else "string"}
                        for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256")
                    ],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": False,
                },
                "mode": "once",
                "options": {"waitForSubWorkflow": True},
            },
            typeVersion=1.3,
            notes="Calls six visible Chatterbox segment nodes, visible assembly/QA routes, native hash, hard gate, and run ledger.",
            retryOnFail=True,
            maxTries=2,
            waitBetweenTries=1000,
        ),
        code(
            "validate_media",
            "Validate Media Sub-workflow Contract",
            2340,
            r"""const i=$input.first(),r=i.json,q=r.audioQa||{};
if(r.mediaValidated!==true||!i.binary?.audio) throw new Error('media proof/audio missing');
if(!/^[a-f0-9]{64}$/.test(String(r.audio_sha256||''))) throw new Error('audio hash missing');
if(!['lxc-137-cpu','rgb-rtx4090'].includes(String(r.ttsProcessor||''))||!r.ttsProcessorLabel||!r.ttsEndpointHost||!r.ttsProfile) throw new Error('TTS processor provenance missing');
if(q.duration_seconds<60||q.integrated_lufs<-18||q.integrated_lufs>-14||q.true_peak_dbtp>-1.5||q.clipped_samples!==0||q.long_silence_ratio>0.08) throw new Error('media QA contract invalid');
return [i];""",
        ),
        node(
            "call_transcription",
            "Run Transcription + SRT Sub-workflow",
            "n8n-nodes-base.executeWorkflow",
            2600,
            {
                "source": "database",
                "workflowId": {"__rl": True, "value": "pTransSubX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-sub-transcription-v1"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {field: "={{ Number($json.episode) }}" if field == "episode" else f"={{{{ $json.{field} }}}}" for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "mediaValidated", "ttsProcessor", "ttsProcessorLabel", "ttsEndpointHost", "ttsProfile")},
                    "matchingColumns": [],
                    "schema": [
                        {"id": field, "displayName": field, "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "array" if field == "selectedStories" else "number" if field == "episode" else "boolean" if field == "mediaValidated" else "object" if field == "audioQa" else "string"}
                        for field in ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "mediaValidated", "ttsProcessor", "ttsProcessorLabel", "ttsEndpointHost", "ttsProfile")
                    ],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": False,
                },
                "mode": "once",
                "options": {"waitForSubWorkflow": True},
            },
            typeVersion=1.3,
            notes="Calls direct Whisper, compact authored-word alignment nodes, native SRT file conversion/hash, hard QA gate, and run ledger.",
        ),
        code(
            "validate_transcription",
            "Validate Transcription Sub-workflow Contract",
            2860,
            r"""const i=$input.first(),r=i.json,a=r.alignment||{};
if(r.transcriptionValidated!==true||!i.binary?.audio||!i.binary?.srt) throw new Error('transcription binaries/proof missing');
if(!/^[a-f0-9]{64}$/.test(String(r.srt_sha256||''))) throw new Error('SRT hash missing');
if(a.wordErrorRate>0.20||a.exactAnchorRatio<0.60||a.maximumLineCharacters>47||a.maximumLinesPerCue>2) throw new Error('transcription QA contract invalid');
if(a.thirds?.map(x=>x.name).join(',')!=='beginning,middle,end') throw new Error('third alignment proof missing');
return [i];""",
        ),
        node(
            "call_distribution",
            "Run Staging Distribution Sub-workflow",
            "n8n-nodes-base.executeWorkflow",
            3120,
            {
                "source": "database",
                "workflowId": {"__rl": True, "value": "pPortableStgX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-portable-staging-v1"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "runMode": "={{ $json.runMode }}",
                        "publishMode": "={{ $('Portable Shadow Safety Gate').first().json.publishMode }}",
                        "date": "={{ $json.date }}",
                        "runId": "={{ $json.runId }}",
                        "episode": "={{ Number($json.episode) }}",
                        "selectedStories": "={{ $json.selectedStories }}",
                        "scriptText": "={{ $json.scriptText }}",
                        "script_sha256": "={{ $json.script_sha256 }}",
                        "audio_sha256": "={{ $json.audio_sha256 }}",
                        "audioQa": "={{ $json.audioQa }}",
                        "ttsProcessor": "={{ $json.ttsProcessor }}",
                        "ttsProcessorLabel": "={{ $json.ttsProcessorLabel }}",
                        "ttsEndpointHost": "={{ $json.ttsEndpointHost }}",
                        "ttsProfile": "={{ $json.ttsProfile }}",
                        "srt_sha256": "={{ $json.srt_sha256 }}",
                        "alignment": "={{ $json.alignment }}",
                        "transcriptionValidated": "={{ $json.transcriptionValidated }}",
                    },
                    "matchingColumns": [],
                    "schema": [
                        {"id": field, "displayName": field, "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number" if field == "episode" else "array" if field == "selectedStories" else "boolean" if field == "transcriptionValidated" else "object" if field in ("audioQa", "alignment") else "string"}
                        for field in ("runMode", "publishMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "ttsProcessor", "ttsProcessorLabel", "ttsEndpointHost", "ttsProfile", "srt_sha256", "alignment", "transcriptionValidated")
                    ],
                    "attemptToConvertTypes": False,
                    "convertFieldsToString": False,
                },
                "mode": "once",
                "options": {"waitForSubWorkflow": True},
            },
            typeVersion=1.3,
            notes="Calls the visible staging-only Cloudinary, GitHub, rollback-only Postgres shape check, Telegram test notification, and ledger workflow.",
        ),
        code(
            "validate_distribution",
            "Validate Staging Distribution Contract",
            3380,
            r"""const r=$input.first().json;
if(r.distributionValidated!==true||r.publishMode!=='staging'||r.databaseRolledBack!==true) throw new Error('staging distribution proof missing');
if(!String(r.cloudinary?.secureUrl||'').startsWith('https://res.cloudinary.com/')||!/^[a-f0-9]{40}$/.test(String(r.github?.commitSha||''))) throw new Error('staging artifact readback missing');
if(!Number.isInteger(r.telegramMessageId)||r.telegramMessageId<1) throw new Error('test notification proof missing');
return [{json:r}];""",
        ),
        node(
            "stop",
            "Portable Parent Staging Stop",
            "n8n-nodes-base.noOp",
            3640,
            {},
            notes="Hard staging stop. The parent has no schedule and no production destination branch.",
        ),
    ]
    connections: dict = {}
    for source, target in zip((n["name"] for n in nodes), (n["name"] for n in nodes[1:])):
        connect(connections, source, target)
    workflow = {
        "id": WORKFLOW_ID,
        "name": WORKFLOW_NAME,
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "availableInMCP": True},
        "meta": {"templateCredsSetupCompleted": True},
        "pinData": {},
        "tags": [],
    }
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger"):
        if forbidden in raw:
            raise ValueError(f"parent contains forbidden value: {forbidden}")
    if workflow["active"]:
        raise ValueError("portable parent must remain inactive")
    if len([n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]) != 5:
        raise ValueError("intake/authoring/media/transcription/distribution sub-workflow calls missing")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
