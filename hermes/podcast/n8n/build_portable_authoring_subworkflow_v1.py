#!/usr/bin/env python3
"""Build the portable three-attempt podcast authoring sub-workflow."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-sub-authoring-v1.json"
WORKFLOW_ID = "pAuthorSubX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-authoring-v1"
VALIDATOR_ID = "pScriptValX8Q3M7"
OLLAMA_CREDENTIAL = {"ollamaApi": {"id": "3QQRE0XvtKk5UsPB", "name": "Ollama Cloud (podcast)"}}


def node(node_id: str, name: str, node_type: str, x: int, y: int, parameters: dict, **extra: object) -> dict:
    result = {"id": node_id, "name": name, "type": node_type, "typeVersion": extra.pop("typeVersion", 1), "position": [x, y], "parameters": parameters}
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, y: int, js: str, notes: str = "") -> dict:
    return node(node_id, name, "n8n-nodes-base.code", x, y, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()}, typeVersion=2, notes=notes)


def connect(connections: dict, source: str, target: str, output: int = 0, target_input: int = 0, connection_type: str = "main") -> None:
    connections.setdefault(source, {}).setdefault(connection_type, [])
    while len(connections[source][connection_type]) <= output:
        connections[source][connection_type].append([])
    connections[source][connection_type][output].append({"node": target, "type": connection_type, "index": target_input})


def validator_call(node_id: str, name: str, x: int, attempt: int, source_name: str) -> dict:
    return node(
        node_id,
        name,
        "n8n-nodes-base.executeWorkflow",
        x,
        -160,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": VALIDATOR_ID, "mode": "list", "cachedResultName": "WF-podcast-sub-script-validator-v1"},
            "workflowInputs": {
                "mappingMode": "defineBelow",
                "value": {"context": "={{ $json.context }}", "draft": "={{ $json.draft }}", "attempt": attempt},
                "matchingColumns": [],
                "schema": [
                    {"id": "context", "displayName": "context", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "object"},
                    {"id": "draft", "displayName": "draft", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
                    {"id": "attempt", "displayName": "attempt", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
                ],
                "attemptToConvertTypes": False,
                "convertFieldsToString": True,
            },
            "mode": "once",
            "options": {"waitForSubWorkflow": True},
        },
        typeVersion=1.3,
        notes=f"Attempt {attempt} calls the same reusable validator sub-workflow; input context comes from {source_name}.",
    )


def valid_if(node_id: str, name: str, x: int, condition_id: str) -> dict:
    return node(
        node_id,
        name,
        "n8n-nodes-base.if",
        x,
        -160,
        {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2}, "conditions": [{"id": condition_id, "leftValue": "={{ $json.authoringValid }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"}, "options": {}},
        typeVersion=2.3,
    )


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    manual_context = {"runMode": "shadow", "date": fixture["date"], "runId": "authoring-fixture/run37", "attempt": 1, "episode": fixture["episode"], "selectedStories": fixture["selectedStories"]}
    nodes = [
        node("manual", "Manual Authoring Test Trigger", "n8n-nodes-base.manualTrigger", 0, -300, {}),
        node("sub_trigger", "When Called by Parent Workflow", "n8n-nodes-base.executeWorkflowTrigger", 0, -60, {"inputSource": "jsonExample", "jsonExample": json.dumps({"runMode": "shadow", "date": "2026-08-08", "runId": "portable-shadow/example", "attempt": 1, "episode": 125, "selectedStories": []}, indent=2)}, typeVersion=1.2),
        code("fixture", "Prepare Authoring Fixture", 240, -300, "return [{json:" + json.dumps(manual_context, separators=(",", ":")) + "}];"),
        code(
            "validate_request",
            "Validate Authoring Request",
            480,
            -160,
            r"""const r=$input.first().json;
if(r.runMode!=='shadow') throw new Error('authoring accepts shadow mode only');
if(!/^\d{4}-\d{2}-\d{2}$/.test(String(r.date||''))) throw new Error('invalid date');
if(!Number.isInteger(r.episode)||r.episode<1) throw new Error('invalid episode');
if(!Array.isArray(r.selectedStories)||r.selectedStories.length!==4) throw new Error('authoring requires four selected stories');
return [{json:r}];""",
        ),
        code(
            "episode_words",
            "Format Spoken Episode Number",
            720,
            -160,
            r"""const r=$input.first().json;const ones=['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen'];const tens=['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety'];
const under=n=>{const p=[];if(n>=100){p.push(ones[Math.floor(n/100)],'hundred');n%=100;}if(n>=20){p.push(tens[Math.floor(n/10)]);if(n%10)p.push(ones[n%10]);}else if(n)p.push(ones[n]);return p.join(' ');};
const n=r.episode;if(n>999999) throw new Error('episode number exceeds spoken formatter');
const episodeSpoken=n<1000?under(n):`${under(Math.floor(n/1000))} thousand${n%1000?' '+under(n%1000):''}`;
const dayName=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'long'}).format(new Date(`${r.date}T12:00:00-04:00`));
return [{json:{...r,episodeSpoken,dayName}}];""",
        ),
        code(
            "prompt",
            "Build Six-Paragraph Author Prompt",
            960,
            -160,
            r"""const r=$input.first().json;
const rules=`Write a 60-90 second spoken script. Hard acceptance range: 330-400 words; target 365-390. Use a rambling, self-interrupting blue-collar everyman voice enthusiastic about AI, with at most one exact chuckle: Heh. Hhh, okay, that's something. No stage directions.\n\nExactly 6 paragraphs separated by blank lines:\n1. Good morning, it's ${r.dayName}. This is Guru's Tech Bytes, episode ${r.episodeSpoken}. Never put digits in the greeting.\n2. Lead with First up...\n3. Lead with Second...\n4. Lead with Third...\n5. Lead with And finally...\n6. Exactly: That's your daily byte. Have a great day. Until next time.\n\nOutput only script text.`;
const stories=r.selectedStories.map((s,i)=>`${i+1}. ${s.title} (${Number(s.score||0)} upvotes)`).join('\n');
return [{json:{...r,authorPrompt:`${rules}\n\nThe four stories, in order:\n${stories}`,authoringAttempt:1}}];""",
        ),
        node("chain1", "Author Script Attempt 1 (GLM-5.2)", "@n8n/n8n-nodes-langchain.chainLlm", 1200, -160, {"promptType": "define", "text": "={{ $json.authorPrompt }}", "hasOutputParser": False, "batching": {"batchSize": 1, "delayBetweenBatches": 0}}, typeVersion=1.9),
        node("model1", "Ollama Cloud GLM-5.2 Attempt 1", "@n8n/n8n-nodes-langchain.lmChatOllama", 1200, 60, {"model": "glm-5.2", "options": {"think": False, "temperature": 0.2, "numCtx": 8192, "numPredict": 700}}, typeVersion=1, credentials=OLLAMA_CREDENTIAL),
        code("validation_input1", "Prepare Validation Attempt 1", 1440, -160, r"""const raw=$input.first().json;return [{json:{context:$('Build Six-Paragraph Author Prompt').first().json,draft:String(raw.text??raw.output??raw.response??raw.content??''),attempt:1}}];"""),
        validator_call("validator1", "Run Reusable Validator - Attempt 1", 1680, 1, "Build Six-Paragraph Author Prompt"),
        valid_if("valid1", "Script Valid Attempt 1?", 1920, "valid-1"),
        node("chain2", "Author Script Attempt 2 (GLM-5.2)", "@n8n/n8n-nodes-langchain.chainLlm", 2160, -40, {"promptType": "define", "text": "={{ $json.authorPrompt }}", "hasOutputParser": False, "batching": {"batchSize": 1, "delayBetweenBatches": 0}}, typeVersion=1.9),
        node("model2", "Ollama Cloud GLM-5.2 Attempt 2", "@n8n/n8n-nodes-langchain.lmChatOllama", 2160, 180, {"model": "glm-5.2", "options": {"think": False, "temperature": 0.2, "numCtx": 8192, "numPredict": 700}}, typeVersion=1, credentials=OLLAMA_CREDENTIAL),
        code("validation_input2", "Prepare Validation Attempt 2", 2400, -40, r"""const raw=$input.first().json;return [{json:{context:$('Run Reusable Validator - Attempt 1').first().json,draft:String(raw.text??raw.output??raw.response??raw.content??''),attempt:2}}];"""),
        validator_call("validator2", "Run Reusable Validator - Attempt 2", 2640, 2, "Run Reusable Validator - Attempt 1"),
        valid_if("valid2", "Script Valid Attempt 2?", 2880, "valid-2"),
        node("chain3", "Author Script Attempt 3 (GLM-5.2)", "@n8n/n8n-nodes-langchain.chainLlm", 3120, 80, {"promptType": "define", "text": "={{ $json.authorPrompt }}", "hasOutputParser": False, "batching": {"batchSize": 1, "delayBetweenBatches": 0}}, typeVersion=1.9),
        node("model3", "Ollama Cloud GLM-5.2 Attempt 3", "@n8n/n8n-nodes-langchain.lmChatOllama", 3120, 300, {"model": "glm-5.2", "options": {"think": False, "temperature": 0.2, "numCtx": 8192, "numPredict": 700}}, typeVersion=1, credentials=OLLAMA_CREDENTIAL),
        code("validation_input3", "Prepare Validation Attempt 3", 3360, 80, r"""const raw=$input.first().json;return [{json:{context:$('Run Reusable Validator - Attempt 2').first().json,draft:String(raw.text??raw.output??raw.response??raw.content??''),attempt:3}}];"""),
        validator_call("validator3", "Run Reusable Validator - Attempt 3", 3600, 3, "Run Reusable Validator - Attempt 2"),
        valid_if("valid3", "Script Valid Attempt 3?", 3840, "valid-3"),
        node("fail", "Fail Authoring After 3 Attempts", "n8n-nodes-base.stopAndError", 4080, 160, {"errorType": "errorMessage", "errorMessage": "={{ $json.failureMessage }}"}, typeVersion=1),
        code(
            "approved",
            "Build Approved Authoring Contract",
            4080,
            -160,
            r"""const r=$input.first().json;const failures=[];
if(r.authoringValidated!==true) failures.push('validation');
if(!Array.isArray(r.selectedStories)||r.selectedStories.length!==4) failures.push('stories');
if(typeof r.scriptText!=='string'||r.scriptText.trim().split(/\s+/).length!==r.wordCount) failures.push('word count');
if(r.paragraphCount!==6) failures.push('paragraph count');
if(failures.length) throw new Error(`approved authoring contract: ${failures.join(', ')}`);
return [{json:r}];""",
        ),
        node("hash", "SHA256 Approved Script", "n8n-nodes-base.crypto", 4320, -160, {"action": "hash", "binaryData": False, "type": "SHA256", "value": "={{ $json.scriptText }}", "dataPropertyName": "script_sha256", "encoding": "hex"}, typeVersion=2),
        node(
            "ledger",
            "Ledger - Authoring Approved",
            "n8n-nodes-base.dataTable",
            4560,
            -160,
            {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "={{ $json.runId }}", "execution_id": "={{ $execution.id }}", "run_mode": "shadow", "episode": "={{ $json.episode }}", "episode_date": "={{ $json.date }}", "stage": "authoring-approved", "status": "passed", "attempt": "={{ $json.authoringAttempt }}", "selected_stories_json": "={{ JSON.stringify($json.selectedStories) }}", "script_sha256": "={{ $json.script_sha256 }}", "audio_sha256": "", "srt_sha256": "", "qa_json": "={{ JSON.stringify({wordCount:$json.wordCount,paragraphCount:$json.paragraphCount,provider:$json.scriptProvider,model:$json.scriptModel}) }}", "artifact_urls_json": "", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}},
            typeVersion=1.1,
        ),
        code("return", "Return Authoring Contract", 4800, -160, r"""return [{json:$('SHA256 Approved Script').first().json}];"""),
    ]

    connections: dict = {}
    connect(connections, "Manual Authoring Test Trigger", "Prepare Authoring Fixture")
    connect(connections, "Prepare Authoring Fixture", "Validate Authoring Request")
    connect(connections, "When Called by Parent Workflow", "Validate Authoring Request")
    for source, target in zip(["Validate Authoring Request", "Format Spoken Episode Number", "Build Six-Paragraph Author Prompt", "Author Script Attempt 1 (GLM-5.2)", "Prepare Validation Attempt 1", "Run Reusable Validator - Attempt 1"], ["Format Spoken Episode Number", "Build Six-Paragraph Author Prompt", "Author Script Attempt 1 (GLM-5.2)", "Prepare Validation Attempt 1", "Run Reusable Validator - Attempt 1", "Script Valid Attempt 1?"]):
        connect(connections, source, target)
    connect(connections, "Ollama Cloud GLM-5.2 Attempt 1", "Author Script Attempt 1 (GLM-5.2)", connection_type="ai_languageModel")
    connect(connections, "Script Valid Attempt 1?", "Build Approved Authoring Contract", output=0)
    connect(connections, "Script Valid Attempt 1?", "Author Script Attempt 2 (GLM-5.2)", output=1)
    for source, target in zip(["Author Script Attempt 2 (GLM-5.2)", "Prepare Validation Attempt 2", "Run Reusable Validator - Attempt 2"], ["Prepare Validation Attempt 2", "Run Reusable Validator - Attempt 2", "Script Valid Attempt 2?"]):
        connect(connections, source, target)
    connect(connections, "Ollama Cloud GLM-5.2 Attempt 2", "Author Script Attempt 2 (GLM-5.2)", connection_type="ai_languageModel")
    connect(connections, "Script Valid Attempt 2?", "Build Approved Authoring Contract", output=0)
    connect(connections, "Script Valid Attempt 2?", "Author Script Attempt 3 (GLM-5.2)", output=1)
    for source, target in zip(["Author Script Attempt 3 (GLM-5.2)", "Prepare Validation Attempt 3", "Run Reusable Validator - Attempt 3"], ["Prepare Validation Attempt 3", "Run Reusable Validator - Attempt 3", "Script Valid Attempt 3?"]):
        connect(connections, source, target)
    connect(connections, "Ollama Cloud GLM-5.2 Attempt 3", "Author Script Attempt 3 (GLM-5.2)", connection_type="ai_languageModel")
    connect(connections, "Script Valid Attempt 3?", "Build Approved Authoring Contract", output=0)
    connect(connections, "Script Valid Attempt 3?", "Fail Authoring After 3 Attempts", output=1)
    for source, target in zip(["Build Approved Authoring Contract", "SHA256 Approved Script", "Ledger - Authoring Approved"], ["SHA256 Approved Script", "Ledger - Authoring Approved", "Return Authoring Contract"]):
        connect(connections, source, target)

    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "httprequest"):
        if forbidden in raw:
            raise ValueError(f"authoring workflow contains forbidden value: {forbidden}")
    if len([n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]) != 3:
        raise ValueError("all three attempts must call the reusable validator")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            lines = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(lines) > 25:
                raise ValueError(f"authoring Code node too large: {item['name']} ({len(lines)} lines)")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
