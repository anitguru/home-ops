#!/usr/bin/env python3
"""Build the portable podcast intake/ranking sub-workflow.

The workflow is intentionally self-contained and canvas-visible: native
Supabase and Hacker News nodes provide data, while small Code nodes normalize,
deduplicate, score, and select. There is no SSH or podcast-worker API.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-sub-intake-v1.json"
WORKFLOW_ID = "pIntakeSubX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-intake-v1"
LEDGER_NAME = "podcast_run_ledger"
SUPABASE_CREDENTIAL = {"supabaseApi": {"id": "duPN6Njb1go7DN8w", "name": "Supabase (podcast)"}}


def node(node_id: str, name: str, node_type: str, x: int, y: int, parameters: dict, **extra: object) -> dict:
    result = {
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": extra.pop("typeVersion", 1),
        "position": [x, y],
        "parameters": parameters,
    }
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, y: int, js: str, notes: str = "") -> dict:
    return node(
        node_id,
        name,
        "n8n-nodes-base.code",
        x,
        y,
        {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()},
        typeVersion=2,
        notes=notes,
    )


def connect(connections: dict, source: str, target: str, target_input: int = 0) -> None:
    connections.setdefault(source, {"main": [[]]})["main"][0].append(
        {"node": target, "type": "main", "index": target_input}
    )


def build() -> dict:
    nodes = [
        node("manual", "Manual Intake Test Trigger", "n8n-nodes-base.manualTrigger", 0, -160, {}),
        node(
            "sub_trigger",
            "When Called by Parent Workflow",
            "n8n-nodes-base.executeWorkflowTrigger",
            0,
            80,
            {
                "inputSource": "jsonExample",
                "jsonExample": json.dumps(
                    {"runMode": "shadow", "date": "2026-08-08", "runId": "portable-shadow/2026-08-08/example", "attempt": 1},
                    indent=2,
                ),
            },
            typeVersion=1.2,
            notes="Reusable entry point. The parent passes runMode/date/runId; no host path or secret is accepted.",
        ),
        code(
            "manual_input",
            "Prepare Manual Shadow Input",
            240,
            -160,
            r"""const now = new Date();
const date = new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
return [{json:{runMode:'shadow',date,runId:`intake-manual/${date}/${$execution.id}`,attempt:1}}];""",
        ),
        code(
            "validate",
            "Validate Intake Request",
            480,
            0,
            r"""const request = $input.first().json;
if (request.runMode !== 'shadow') throw new Error('intake sub-workflow accepts shadow mode only');
if (!/^\d{4}-\d{2}-\d{2}$/.test(String(request.date || ''))) throw new Error('invalid ET date');
if (!/^[A-Za-z0-9/_-]+$/.test(String(request.runId || ''))) throw new Error('invalid run ID');
return [{json:{runMode:'shadow',date:request.date,runId:request.runId,attempt:Number(request.attempt || 1)}}];""",
        ),
        node(
            "supabase_date",
            "Supabase - Find Episode for Date",
            "n8n-nodes-base.supabase",
            720,
            -120,
            {
                "resource": "row",
                "operation": "getAll",
                "tableId": "podcast_episodes",
                "returnAll": False,
                "limit": 1,
                "orderBy": "episode.desc",
                "filterType": "manual",
                "matchType": "allFilters",
                "filters": {"conditions": [{"keyName": "date", "condition": "eq", "keyValue": "={{ $json.date }}"}]},
            },
            typeVersion=1,
            credentials=SUPABASE_CREDENTIAL,
            alwaysOutputData=True,
        ),
        node(
            "supabase_latest",
            "Supabase - Get Latest Episode",
            "n8n-nodes-base.supabase",
            720,
            120,
            {
                "resource": "row",
                "operation": "getAll",
                "tableId": "podcast_episodes",
                "returnAll": False,
                "limit": 1,
                "orderBy": "episode.desc",
                "filterType": "none",
            },
            typeVersion=1,
            credentials=SUPABASE_CREDENTIAL,
            alwaysOutputData=True,
        ),
        node(
            "merge_episode",
            "Merge Supabase Episode Lookups",
            "n8n-nodes-base.merge",
            960,
            0,
            {"mode": "combine", "combineBy": "combineByPosition", "options": {}},
            typeVersion=3.2,
        ),
        code(
            "choose_episode",
            "Choose Idempotent Episode Number",
            1200,
            0,
            r"""const request = $('Validate Intake Request').first().json;
const sameDate = $('Supabase - Find Episode for Date').first().json;
const latest = $('Supabase - Get Latest Episode').first().json;
const episode = Number(sameDate.episode || 0) || (Number(latest.episode || 0) + 1);
if (!Number.isInteger(episode) || episode < 1) throw new Error('Supabase returned no valid episode number');
return [{json:{...request,episode,episodeSource:sameDate.episode?'existing-date':'latest-plus-one'}}];""",
        ),
        node(
            "hacker_news",
            "Hacker News - Get Front Page",
            "n8n-nodes-base.hackerNews",
            1440,
            0,
            {"resource": "all", "operation": "getAll", "returnAll": False, "limit": 20, "additionalFields": {"tags": ["front_page"]}},
            typeVersion=1,
            notes="Native Hacker News node; this maps to the same Algolia front_page feed previously called through HTTP.",
        ),
        code(
            "normalize",
            "Normalize Hacker News Stories",
            1680,
            0,
            r"""const context = $('Choose Idempotent Episode Number').first().json;
const stories = $input.all().map(({json:s}) => ({
  id:String(s.objectID || s.id || ''),
  title:String(s.title || s.story_title || '').replace(/\s+/g,' ').trim(),
  url:String(s.url || s.story_url || '').trim(),
  hnUrl:`https://news.ycombinator.com/item?id=${s.objectID || s.id}`,
  score:Number(s.points || s.score || 0),
  createdAt:s.created_at || null,
})).filter(s => /^https?:\/\//.test(s.url) && s.id && s.title);
if (stories.length < 4) throw new Error(`only ${stories.length} usable Hacker News stories`);
return [{json:{...context,stories}}];""",
        ),
        code(
            "domain",
            "Deduplicate Story Domains",
            1920,
            0,
            r"""const context = $input.first().json;
const seen = new Set();
const stories = context.stories.filter(story => {
  const domain = story.url.replace(/^https?:\/\//i,'').split('/')[0].split(':')[0].toLowerCase().replace(/^www\./,'');
  if (!domain || !domain.includes('.')) return false;
  if (seen.has(domain)) return false;
  seen.add(domain); story.domain = domain; return true;
});
if (stories.length < 4) throw new Error(`only ${stories.length} domain-diverse stories`);
return [{json:{...context,stories}}];""",
        ),
        code(
            "topics",
            "Score Technology Topic Matches",
            2160,
            0,
            r"""const context = $input.first().json;
const topics=['ai','openai','llm','model','linux','security','database','postgres','supabase','cloud','developer','programming','python','javascript','hardware','chip','robot','network','privacy','browser','github'];
const stories=context.stories.map(story=>{
  const haystack=`${story.title} ${story.url}`.toLowerCase();
  const matchedTopics=topics.filter(topic=>haystack.includes(topic));
  return {...story,matchedTopics,rankScore:story.score + matchedTopics.length*120};
});
return [{json:{...context,stories}}];""",
            "Small reusable scoring transform. Weight and topic vocabulary are visible and versioned in this node.",
        ),
        code(
            "sort",
            "Sort Ranked Candidates",
            2400,
            0,
            r"""const context=$input.first().json;
const stories=[...context.stories].sort((a,b)=>b.rankScore-a.rankScore || b.score-a.score || a.id.localeCompare(b.id));
return [{json:{...context,stories}}];""",
        ),
        code(
            "select",
            "Select Four Stories",
            2640,
            0,
            r"""const context=$input.first().json;
const selectedStories=context.stories.slice(0,4).map(({rankScore,domain,...story},index)=>({...story,rank:index+1,domain,rankScore}));
if (selectedStories.length !== 4 || new Set(selectedStories.map(s=>s.domain)).size !== 4) throw new Error('four-story selection proof failed');
return [{json:{runMode:context.runMode,date:context.date,runId:context.runId,attempt:context.attempt,episode:context.episode,episodeSource:context.episodeSource,selectedStories,candidateCount:context.stories.length,rankingProof:{algorithm:'visible-topic-score-v1',domainDiverse:true,selectedCount:4}}}];""",
        ),
        node(
            "ledger",
            "Ledger - Intake Selected",
            "n8n-nodes-base.dataTable",
            2880,
            0,
            {
                "resource": "row",
                "operation": "insert",
                "dataTableId": {"mode": "name", "value": LEDGER_NAME},
                "columns": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "run_id": "={{ $json.runId }}",
                        "execution_id": "={{ $execution.id }}",
                        "run_mode": "shadow",
                        "episode": "={{ $json.episode }}",
                        "episode_date": "={{ $json.date }}",
                        "stage": "intake-selected",
                        "status": "passed",
                        "attempt": "={{ $json.attempt }}",
                        "selected_stories_json": "={{ JSON.stringify($json.selectedStories) }}",
                        "script_sha256": "",
                        "audio_sha256": "",
                        "srt_sha256": "",
                        "qa_json": "={{ JSON.stringify($json.rankingProof) }}",
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
        code(
            "restore",
            "Return Intake Contract",
            3120,
            0,
            r"""return [{json:$('Select Four Stories').first().json}];""",
            "The last node returns the stable contract to the parent workflow.",
        ),
    ]

    connections: dict = {}
    connect(connections, "Manual Intake Test Trigger", "Prepare Manual Shadow Input")
    connect(connections, "Prepare Manual Shadow Input", "Validate Intake Request")
    connect(connections, "When Called by Parent Workflow", "Validate Intake Request")
    connect(connections, "Validate Intake Request", "Supabase - Find Episode for Date")
    connect(connections, "Validate Intake Request", "Supabase - Get Latest Episode")
    connect(connections, "Supabase - Find Episode for Date", "Merge Supabase Episode Lookups", 0)
    connect(connections, "Supabase - Get Latest Episode", "Merge Supabase Episode Lookups", 1)
    linear = [
        "Merge Supabase Episode Lookups",
        "Choose Idempotent Episode Number",
        "Hacker News - Get Front Page",
        "Normalize Hacker News Stories",
        "Deduplicate Story Domains",
        "Score Technology Topic Matches",
        "Sort Ranked Candidates",
        "Select Four Stories",
        "Ledger - Intake Selected",
        "Return Intake Contract",
    ]
    for source, target in zip(linear, linear[1:]):
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
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "http://hn.algolia.com", "https://hn.algolia.com"):
        if forbidden in raw:
            raise ValueError(f"intake workflow contains forbidden value: {forbidden}")
    if workflow["active"]:
        raise ValueError("sub-workflow must remain inactive while validating")
    if not any(n["type"] == "n8n-nodes-base.supabase" for n in workflow["nodes"]):
        raise ValueError("native Supabase node missing")
    if not any(n["type"] == "n8n-nodes-base.hackerNews" for n in workflow["nodes"]):
        raise ValueError("native Hacker News node missing")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            lines = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(lines) > 40:
                raise ValueError(f"Code node too large: {item['name']} ({len(lines)} lines)")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
