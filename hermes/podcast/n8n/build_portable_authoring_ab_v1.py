#!/usr/bin/env python3
"""Build a visible, distribution-free GLM-5.2 versus DeepSeek authoring harness."""

from __future__ import annotations

import json
from pathlib import Path

import build_portable_authoring_subworkflow_v1 as authoring


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-authoring-ab-v1.json"
WORKFLOW_ID = "pAuthorABX8Q3M7"
WORKFLOW_NAME = "WF-podcast-authoring-ab-v1"


def call_node(node_id: str, name: str, workflow_id: str, workflow_name: str, x: int, y: int) -> dict:
    schema = [
        {"id": "runMode", "displayName": "runMode", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
        {"id": "date", "displayName": "date", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
        {"id": "runId", "displayName": "runId", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "string"},
        {"id": "attempt", "displayName": "attempt", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
        {"id": "episode", "displayName": "episode", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "number"},
        {"id": "selectedStories", "displayName": "selectedStories", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "array"},
    ]
    values = {key: "={{ $('Validate A/B Request').first().json." + key + " }}" for key in ("runMode", "date", "runId", "attempt", "episode", "selectedStories")}
    return authoring.node(
        node_id, name, "n8n-nodes-base.executeWorkflow", x, y,
        {"source": "database", "workflowId": {"__rl": True, "value": workflow_id, "mode": "list", "cachedResultName": workflow_name}, "workflowInputs": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [], "schema": schema, "attemptToConvertTypes": False, "convertFieldsToString": False}, "mode": "once", "options": {"waitForSubWorkflow": True}},
        typeVersion=1.3,
    )


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    context = {"runMode": "shadow", "date": fixture["date"], "runId": "authoring-ab/run37", "attempt": 1, "episode": fixture["episode"], "selectedStories": fixture["selectedStories"]}
    nodes = [
        authoring.node("manual", "Manual Authoring A/B Trigger", "n8n-nodes-base.manualTrigger", 0, -260, {}),
        authoring.node("called", "When Called with Four Stories", "n8n-nodes-base.executeWorkflowTrigger", 0, 40, {"inputSource": "jsonExample", "jsonExample": json.dumps(context, indent=2)}, typeVersion=1.2),
        authoring.code("fixture", "Prepare Frozen A/B Fixture", 240, -260, "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];"),
        authoring.code("validate", "Validate A/B Request", 480, -100, r"""const r=$input.first().json;
if(r.runMode!=='shadow'||!Array.isArray(r.selectedStories)||r.selectedStories.length!==4) throw new Error('A/B requires four shadow stories');
return [{json:{...r,runId:`${r.runId}/${$execution.id}`}}];"""),
        call_node("glm", "Run GLM-5.2 Authoring Candidate", "pAuthorSubX8Q3M7", "WF-podcast-sub-authoring-v1", 760, -220),
        call_node("deepseek", "Run DeepSeek 0731 Authoring Candidate", "pAuthorDSX8Q3M7", "WF-podcast-sub-authoring-deepseek-v1", 760, 100),
        authoring.code("label_glm", "Label GLM Candidate", 1040, -220, "return [{json:{candidate:'glm-5.2',result:$input.first().json}}];"),
        authoring.code("label_ds", "Label DeepSeek Candidate", 1040, 100, "return [{json:{candidate:'deepseek-v4-flash:0731-cloud',result:$input.first().json}}];"),
        authoring.node("merge", "Merge Both Authoring Candidates", "n8n-nodes-base.merge", 1280, -60, {"mode": "append", "options": {}}, typeVersion=3.2),
        authoring.code("compare", "Build Objective A/B Comparison", 1520, -60, r"""const rows=$input.all().map(i=>i.json);const by=Object.fromEntries(rows.map(r=>[r.candidate,r.result]));
const glm=by['glm-5.2'],deepseek=by['deepseek-v4-flash:0731-cloud'];if(!glm||!deepseek)throw new Error('both A/B candidates are required');
const summary=r=>({model:r.scriptModel,validated:r.authoringValidated,attempt:r.authoringAttempt,wordCount:r.wordCount,paragraphCount:r.paragraphCount,scriptSha256:r.script_sha256,scriptText:r.scriptText});
return [{json:{runId:glm.runId,date:glm.date,episode:glm.episode,selectedStories:glm.selectedStories,glm:summary(glm),deepseek:summary(deepseek),objectiveComplete:true,humanPreference:'pending'}}];"""),
        authoring.node("ledger", "Ledger - Authoring A/B Complete", "n8n-nodes-base.dataTable", 1760, -60, {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "={{ $json.runId }}", "execution_id": "={{ $execution.id }}", "run_mode": "authoring-ab", "episode": "={{ $json.episode }}", "episode_date": "={{ $json.date }}", "stage": "authoring-ab-complete", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($json.selectedStories) }}", "script_sha256": "", "audio_sha256": "", "srt_sha256": "", "qa_json": "={{ JSON.stringify({glm:$json.glm,deepseek:$json.deepseek,humanPreference:$json.humanPreference}) }}", "artifact_urls_json": "", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1),
        authoring.code("return", "Return Authoring A/B Contract", 2000, -60, "return [{json:$('Build Objective A/B Comparison').first().json}];"),
    ]
    connections: dict = {}
    authoring.connect(connections, "Manual Authoring A/B Trigger", "Prepare Frozen A/B Fixture")
    authoring.connect(connections, "Prepare Frozen A/B Fixture", "Validate A/B Request")
    authoring.connect(connections, "When Called with Four Stories", "Validate A/B Request")
    authoring.connect(connections, "Validate A/B Request", "Run GLM-5.2 Authoring Candidate")
    authoring.connect(connections, "Validate A/B Request", "Run DeepSeek 0731 Authoring Candidate")
    authoring.connect(connections, "Run GLM-5.2 Authoring Candidate", "Label GLM Candidate")
    authoring.connect(connections, "Run DeepSeek 0731 Authoring Candidate", "Label DeepSeek Candidate")
    authoring.connect(connections, "Label GLM Candidate", "Merge Both Authoring Candidates", target_input=0)
    authoring.connect(connections, "Label DeepSeek Candidate", "Merge Both Authoring Candidates", target_input=1)
    authoring.connect(connections, "Merge Both Authoring Candidates", "Build Objective A/B Comparison")
    authoring.connect(connections, "Build Objective A/B Comparison", "Ledger - Authoring A/B Complete")
    authoring.connect(connections, "Ledger - Authoring A/B Complete", "Return Authoring A/B Contract")
    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "httprequest"):
        if forbidden in raw:
            raise ValueError(f"A/B workflow contains forbidden value: {forbidden}")
    forbidden_types = {"n8n-nodes-base.cloudinary", "n8n-nodes-base.telegram", "n8n-nodes-base.github", "n8n-nodes-base.supabase"}
    if any(n["type"] in forbidden_types for n in workflow["nodes"]):
        raise ValueError("A/B harness must not contain distribution nodes")
    if len([n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]) != 2:
        raise ValueError("A/B harness must call exactly two authoring candidates")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
