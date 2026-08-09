#!/usr/bin/env python3
"""Build the reusable podcast script-validation sub-workflow."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-sub-script-validator-v1.json"
WORKFLOW_ID = "pScriptValX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-script-validator-v1"


def node(node_id: str, name: str, node_type: str, x: int, y: int, parameters: dict, **extra: object) -> dict:
    result = {"id": node_id, "name": name, "type": node_type, "typeVersion": extra.pop("typeVersion", 1), "position": [x, y], "parameters": parameters}
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, y: int, js: str, notes: str = "") -> dict:
    return node(node_id, name, "n8n-nodes-base.code", x, y, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()}, typeVersion=2, notes=notes)


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    manual = {
        "context": {
            "runMode": "shadow",
            "date": fixture["date"],
            "runId": "validator-fixture/run37",
            "episode": fixture["episode"],
            "episodeSpoken": "one hundred twenty five",
            "dayName": "Saturday",
            "selectedStories": fixture["selectedStories"],
            "authorPrompt": "fixture validator prompt",
        },
        "draft": fixture["scriptText"],
        "attempt": 1,
    }
    nodes = [
        node("manual", "Manual Validator Test Trigger", "n8n-nodes-base.manualTrigger", 0, -140, {}),
        node(
            "sub_trigger",
            "When Called by Authoring Workflow",
            "n8n-nodes-base.executeWorkflowTrigger",
            0,
            100,
            {"inputSource": "jsonExample", "jsonExample": json.dumps({"context": None, "draft": "script text", "attempt": 1}, indent=2)},
            typeVersion=1.2,
        ),
        code("fixture", "Prepare Validator Fixture", 240, -140, "return [{json:" + json.dumps(manual, separators=(",", ":")) + "}];"),
        code(
            "normalize",
            "Normalize Script Draft",
            480,
            0,
            r"""const request=$input.first().json;
if(!request.context||!['shadow','production'].includes(request.context.runMode)) throw new Error('validator requires shadow or production context');
const attempt=Number(request.attempt);
if(![1,2,3].includes(attempt)) throw new Error('validator attempt must be 1-3');
let text=String(request.draft||'').trim();
if(!text) throw new Error('validator received empty draft');
const paragraphs=text.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean);
return [{json:{context:request.context,attempt,text,paragraphs,rawWordCount:text.split(/\s+/).filter(Boolean).length}}];""",
        ),
        code(
            "trim",
            "Trim Overlong Script Safely",
            720,
            0,
            r"""const r=$input.first().json;
let paragraphs=r.paragraphs; let text=r.text; let words=r.rawWordCount; let authoringTrimmed=false;
if(words>400&&paragraphs.length===6){
 const sentences=paragraphs.map(p=>p.split(/(?<=[.!?])\s+/).filter(Boolean));
 while(words>390){
  const choices=[1,2,3,4].filter(i=>sentences[i].length>2).map(i=>({i,count:sentences[i].at(-1).split(/\s+/).length})).filter(x=>words-x.count>=365).sort((a,b)=>b.count-a.count);
  if(!choices.length) break; const chosen=choices[0]; sentences[chosen.i].pop(); words-=chosen.count; authoringTrimmed=true;
 }
 if(authoringTrimmed){paragraphs=sentences.map(x=>x.join(' '));text=paragraphs.join('\n\n');words=text.split(/\s+/).filter(Boolean).length;}
}
return [{json:{...r,text,paragraphs,wordCount:words,authoringTrimmed}}];""",
        ),
        code(
            "structure",
            "Validate Six-Paragraph Structure",
            960,
            0,
            r"""const r=$input.first().json;const p=r.paragraphs;const errors=[];
if(p.length!==6) errors.push(`expected 6 paragraphs, got ${p.length}`);
if(r.wordCount<330||r.wordCount>400) errors.push(`word count ${r.wordCount} outside 330-400`);
const chuckle="Heh. Hhh, okay, that's something.";if(r.text.split(chuckle).length-1>1) errors.push('chuckle used more than once');
const expectedGreeting=`Good morning, it's ${r.context.dayName}. This is Guru's Tech Bytes, episode ${r.context.episodeSpoken}.`;
if(p[0]&&!p[0].startsWith(expectedGreeting)) errors.push(`paragraph 1 must begin with the exact required greeting`);
if(p[0]&&/\d/.test(p[0])) errors.push('paragraph 1 contains digits');
const leakPatterns=[
 ['never put digits',/never put digits/i],['output only',/output only/i],['return only the six narration paragraphs',/return only the six narration paragraphs/i],
 ['lead with',/lead with (?:first up|second|third|and finally)/i],['paragraph specification',/exactly (?:6|six) paragraphs/i],
 ['word-count instruction',/hard acceptance range|target 365(?:-|–)390/i],['validation feedback',/previous draft failed validation|validation errors/i],
 ['rewrite instruction',/rewrite the entire six-paragraph script/i],['narration-only contract',/narration-only contract/i]
];
const promptLeakagePhrases=leakPatterns.filter(([,pattern])=>pattern.test(r.text)).map(([label])=>label);
if(promptLeakagePhrases.length) errors.push(`prompt/meta instruction leaked: ${promptLeakagePhrases.join(', ')}`);
['first up','second','third','and finally'].forEach((lead,i)=>{if(p[i+1]&&!p[i+1].toLowerCase().startsWith(lead)) errors.push(`paragraph ${i+2} must start with ${lead}`);});
if(p.at(-1)&&p.at(-1)!=="That's your daily byte. Have a great day. Until next time.") errors.push('paragraph 6 is not the exact closing');
return [{json:{...r,promptLeakageDetected:promptLeakagePhrases.length>0,promptLeakagePhrases,validationErrors:errors,authoringValid:errors.length===0}}];""",
        ),
        code(
            "contract",
            "Build Validation Contract",
            1200,
            0,
            r"""const r=$input.first().json;const context=r.context;
const originalAuthorPrompt=context.originalAuthorPrompt||context.authorPrompt;
const correctionPrompt=r.authoringValid?context.authorPrompt:[originalAuthorPrompt,'',`Previous draft failed validation on attempt ${r.attempt}.`,'Validation errors:','- '+r.validationErrors.join('\n- '),'','Previous draft:','---',r.text,'---','',`Return 365-390 words; the previous draft had ${r.wordCount}. Rewrite the entire six-paragraph script and fix every error. Output only the corrected script.`].join('\n');
return [{json:{...context,originalAuthorPrompt,authorPrompt:correctionPrompt,priorDraft:r.text,scriptText:r.authoringValid?r.text:null,rawWordCount:r.rawWordCount,wordCount:r.wordCount,authoringTrimmed:r.authoringTrimmed,paragraphCount:r.paragraphs.length,authoringAttempt:r.attempt,authoringValid:r.authoringValid,authoringValidated:r.authoringValid,promptLeakageDetected:r.promptLeakageDetected,promptLeakagePhrases:r.promptLeakagePhrases,validationErrors:r.validationErrors,failureMessage:r.authoringValid?'':`SCRIPT VALIDATION FAIL after attempt ${r.attempt}: ${r.validationErrors.join('; ')}`,scriptProvider:context.scriptProvider||'ollama',scriptModel:context.scriptModel||'glm-5.2'}}];""",
            "Stable result contract used identically by all three bounded authoring attempts.",
        ),
    ]
    connections: dict = {}
    connect(connections, "Manual Validator Test Trigger", "Prepare Validator Fixture")
    connect(connections, "Prepare Validator Fixture", "Normalize Script Draft")
    connect(connections, "When Called by Authoring Workflow", "Normalize Script Draft")
    for source, target in zip(
        ["Normalize Script Draft", "Trim Overlong Script Safely", "Validate Six-Paragraph Structure"],
        ["Trim Overlong Script Safely", "Validate Six-Paragraph Structure", "Build Validation Contract"],
    ):
        connect(connections, source, target)
    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "httprequest"):
        if forbidden in raw:
            raise ValueError(f"validator contains forbidden value: {forbidden}")
    structure = next(n for n in workflow["nodes"] if n["id"] == "structure")["parameters"]["jsCode"]
    if "prompt/meta instruction leaked" not in structure or "promptLeakageDetected" not in structure:
        raise ValueError("validator must hard-fail prompt leakage")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            lines = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(lines) > 25:
                raise ValueError(f"validator Code node too large: {item['name']} ({len(lines)} lines)")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
