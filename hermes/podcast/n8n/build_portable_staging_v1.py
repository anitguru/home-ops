#!/usr/bin/env python3
"""Build a visible, portable staging-distribution workflow.

Every external side effect is a first-class n8n node. CT143 participates only
as n8n's configured external Code-node runner; the graph contains no CT143 API,
SSH, local clone, or podcast-specific filesystem dependency.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-portable-staging-v1.json"

WORKFLOW_ID = "pPortableStgX8Q3M7"
WORKFLOW_NAME = "WF-podcast-portable-staging-v1"
LEDGER_NAME = "podcast_run_ledger"

POSTGRES_CREDENTIAL = {"postgres": {"id": "fK9icsGZqJ3aJWG3", "name": "Supabase Postgres (podcast)"}}
TELEGRAM_CREDENTIAL = {"telegramApi": {"id": "oOpvPw9TPukkiYK6", "name": "Guru's Tech Bytes Bot (podcast)"}}
GITHUB_HTTP_CREDENTIAL = {"httpHeaderAuth": {"id": "pGithubApiX8Q3M7Z", "name": "GitHub API (podcast)"}}
GITHUB_NATIVE_CREDENTIAL = {"githubApi": {"id": "pGithubNodeX8Q3M7Z", "name": "GitHub Node (podcast)"}}
CLOUDINARY_CREDENTIAL = {"cloudinaryApi": {"id": "pCloudinaryX8Q3M7", "name": "Cloudinary (podcast)"}}


def node(node_id: str, name: str, node_type: str, x: int, parameters: dict, **extra: object) -> dict:
    value = {
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": extra.pop("typeVersion", 1),
        "position": [x, 0],
        "parameters": parameters,
    }
    value.update(extra)
    return value


def code_node(node_id: str, name: str, x: int, code: str, notes: str = "") -> dict:
    return node(
        node_id,
        name,
        "n8n-nodes-base.code",
        x,
        {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": code.strip()},
        typeVersion=2,
        notes=notes,
    )


def http_node(
    node_id: str,
    name: str,
    x: int,
    parameters: dict,
    credentials: dict | None = None,
    notes: str = "",
) -> dict:
    result = node(node_id, name, "n8n-nodes-base.httpRequest", x, parameters, typeVersion=4.4, notes=notes)
    if credentials:
        result["credentials"] = credentials
    return result


def ledger_node(node_id: str, name: str, x: int, stage: str, status: str, **fields: str) -> dict:
    values = {
        "run_id": "={{ $('Portable Staging Context').first().json.portableRunId }}",
        "execution_id": "={{ $execution.id }}",
        "run_mode": "shadow",
        "episode": "={{ $('Portable Staging Context').first().json.episode }}",
        "episode_date": "={{ $('Portable Staging Context').first().json.date }}",
        "stage": stage,
        "status": status,
        "attempt": 1,
        "selected_stories_json": "={{ JSON.stringify($('Portable Staging Context').first().json.selectedStories) }}",
        "script_sha256": fields.get("script_sha256", ""),
        "audio_sha256": fields.get("audio_sha256", ""),
        "srt_sha256": "={{ $('Portable Staging Context').first().json.srt.sha256 }}",
        "qa_json": fields.get("qa_json", ""),
        "artifact_urls_json": fields.get("artifact_urls_json", ""),
        "error": "",
        "started_at": "={{ $('Portable Staging Context').first().json.startedAt }}",
        "updated_at": "={{ $now.toISO() }}",
    }
    return node(
        node_id,
        name,
        "n8n-nodes-base.dataTable",
        x,
        {
            "resource": "row",
            "operation": "insert",
            "dataTableId": {"mode": "name", "value": LEDGER_NAME},
            "columns": {"mappingMode": "defineBelow", "value": values},
            "options": {},
        },
        typeVersion=1.1,
    )


def connect(connections: dict, source: str, target: str) -> None:
    connections[source] = {"main": [[{"node": target, "type": "main", "index": 0}]]}


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    fixture_code = "const fixture = " + json.dumps(fixture, separators=(",", ":")) + r""";
const incoming=$input.first();const now=$now.toISO();
if(incoming.binary?.audio&&incoming.binary?.srt){const r=incoming.json;
 if(r.runMode!=='shadow'||r.publishMode!=='staging'||r.transcriptionValidated!==true) throw new Error('staging input mode/proof invalid');
 const seconds=Number(r.audioQa?.duration_seconds);const duration=`${Math.floor(seconds/60)}:${String(Math.round(seconds%60)).padStart(2,'0')}`;
 const sourceExecutionId=String(r.runId).split('/').pop().replace(/[^A-Za-z0-9_-]/g,'');
 return [{json:{...r,sourceExecutionId,portableRunId:r.runId,startedAt:now,inputMode:'parent',audio:{sha256:r.audio_sha256,bytes:0,durationSeconds:seconds,duration},srt:{sha256:r.srt_sha256,alignment:r.alignment}},binary:{audio:incoming.binary.audio,srt:incoming.binary.srt}}];}
return [{json:{...fixture,portableRunId:`portable-staging/${fixture.sourceExecutionId}/${$execution.id}`,startedAt:now,inputMode:'fixture'}}];"""

    nodes: list[dict] = [
        node("manual", "Manual Portable Staging Trigger", "n8n-nodes-base.manualTrigger", 0, {}),
        node("sub_trigger", "When Called by Parent Workflow", "n8n-nodes-base.executeWorkflowTrigger", 0, {"inputSource": "jsonExample", "jsonExample": json.dumps({"runMode": "shadow", "publishMode": "staging", "date": "2026-08-08", "runId": "portable-shadow/example", "episode": 125, "selectedStories": [], "scriptText": "approved", "script_sha256": "0" * 64, "audio_sha256": "0" * 64, "audioQa": {"duration_seconds": 120}, "srt_sha256": "0" * 64, "alignment": {}, "transcriptionValidated": True}, indent=2)}, typeVersion=1.2, position=[0, 180]),
        code_node("context", "Portable Staging Context", 240, fixture_code, "Frozen execution-37 fixture; no credential, path, or worker URL."),
        ledger_node("ledger_start", "Ledger - Staging Started", 480, "staging-start", "running"),
        node(
            "input_mode", "Incoming Parent Audio?", "n8n-nodes-base.if", 600,
            {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2}, "conditions": [{"id": "parent-input", "leftValue": "={{ $('Portable Staging Context').first().json.inputMode }}", "rightValue": "parent", "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"}, "options": {}}, typeVersion=2.3,
        ),
        code_node(
            "restore_audio", "Restore Incoming Audio Binary", 720,
            r"""const c=$('Portable Staging Context').first();
if(!c.binary?.audio) throw new Error('incoming staging audio binary missing');
return [{json:c.json,binary:{audio:c.binary.audio,srt:c.binary.srt}}];""",
        ),
        http_node(
            "download_audio",
            "Download Verified Audio from Cloudinary",
            720,
            {
                "url": "={{ $('Portable Staging Context').first().json.audio.sourceUrl }}",
                "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "audio"}}, "timeout": 120000},
            },
            notes="HTTP exception: the verified Cloudinary node has upload/search/asset operations but no binary download operation.",
        ),
        node(
            "hash_audio",
            "SHA256 Downloaded Audio",
            "n8n-nodes-base.crypto",
            960,
            {
                "action": "hash",
                "binaryData": True,
                "binaryPropertyName": "audio",
                "type": "SHA256",
                "dataPropertyName": "audio_sha256",
                "encoding": "hex",
            },
            typeVersion=2,
        ),
        code_node(
            "validate_audio",
            "Validate Downloaded Audio",
            1200,
            r"""const item = $input.first();
const expected = $('Portable Staging Context').first().json.audio;
if (item.json.audio_sha256 !== expected.sha256) throw new Error('downloaded audio hash mismatch');
return [{json:{audio_sha256:item.json.audio_sha256,hashVerified:true}}];""",
        ),
        node(
            "merge_audio_upload",
            "Merge Audio + Verified Hash",
            "n8n-nodes-base.merge",
            1440,
            {"mode": "combine", "combineBy": "combineByPosition", "options": {}},
            typeVersion=3.2,
            notes="Native merge rejoins the untouched binary item with the separately verified SHA-256 result.",
        ),
        node(
            "upload_audio",
            "Cloudinary - Upload Staging Audio",
            "n8n-nodes-cloudinary.cloudinary",
            1680,
            {
                "resource": "upload",
                "operation": "uploadFile",
                "file": "audio",
                "resource_type_file": "video",
                "additionalFieldsFile": {
                    "folder": "anitguru-shadow",
                    "public_id": "={{ 'gurus-tech-bytes-portable-' + $('Portable Staging Context').first().json.date + '-' + $('Portable Staging Context').first().json.sourceExecutionId + '-' + $execution.id }}",
                    "tags": "podcast-shadow,portable-n8n",
                },
            },
            typeVersion=2,
            credentials=CLOUDINARY_CREDENTIAL,
        ),
        code_node(
            "validate_upload",
            "Validate Cloudinary Upload",
            2160,
            r"""const result = $input.first().json;
const fixture = $('Portable Staging Context').first().json;
const targetKey = `anitguru-shadow/gurus-tech-bytes-portable-${fixture.date}-${fixture.sourceExecutionId}-${$execution.id}`;
if (result.public_id !== targetKey) throw new Error('Cloudinary target mismatch');
if (fixture.audio.bytes > 0 && Number(result.bytes) !== fixture.audio.bytes) throw new Error('Cloudinary byte count mismatch');
if (Number(result.bytes) < 100000) throw new Error('Cloudinary upload unexpectedly small');
if (!String(result.secure_url || '').startsWith('https://res.cloudinary.com/')) throw new Error('Cloudinary secure URL missing');
return [{json:{...result,targetKey,audioSha256:fixture.audio.sha256}}];""",
        ),
        http_node(
            "head_audio",
            "HEAD Verify Cloudinary Audio",
            2400,
            {
                "method": "HEAD",
                "url": "={{ $('Validate Cloudinary Upload').first().json.secure_url }}",
                "options": {"response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}}, "timeout": 20000},
            },
            notes="HTTP exception: the verified Cloudinary node has no delivery-URL HEAD operation.",
        ),
        code_node(
            "validate_head",
            "Validate Cloudinary HEAD",
            2640,
            r"""const response = $input.first().json;
if (Number(response.statusCode) < 200 || Number(response.statusCode) >= 400) throw new Error(`Cloudinary HEAD failed: ${response.statusCode}`);
return [{json:{verified:true,statusCode:response.statusCode,secureUrl:$('Validate Cloudinary Upload').first().json.secure_url}}];""",
        ),
        ledger_node(
            "ledger_cloudinary",
            "Ledger - Cloudinary Verified",
            2880,
            "cloudinary",
            "passed",
            audio_sha256="={{ $('Portable Staging Context').first().json.audio.sha256 }}",
            qa_json="={{ JSON.stringify($('Portable Staging Context').first().json.audio) }}",
            artifact_urls_json="={{ JSON.stringify({audio:$('Validate Cloudinary Upload').first().json.secure_url}) }}",
        ),
        code_node(
            "markdown",
            "Generate Episode Markdown",
            3120,
            r"""const fixture = $('Portable Staging Context').first().json;
const audioUrl = $('Validate Cloudinary Upload').first().json.secure_url;
const clean = value => String(value ?? '').replace(/\s+/g,' ').trim();
const title = `${clean(fixture.selectedStories[0]?.title) || "Guru's Tech Bytes"} | EP #${fixture.episode}`;
const stories = fixture.selectedStories.map(s => `  - title: ${JSON.stringify(clean(s.title))}\n    url: ${JSON.stringify(s.url)}\n    hnUrl: ${JSON.stringify(s.hnUrl)}\n    score: ${Number(s.score)}`).join('\n');
const markdown = `---\ntitle: ${JSON.stringify(title)}\nepisode: ${fixture.episode}\ndate: ${JSON.stringify(fixture.date)}\naudioUrl: ${JSON.stringify(audioUrl)}\naudioLength: ${$('Validate Cloudinary Upload').first().json.bytes}\nduration: ${JSON.stringify(fixture.audio.duration)}\nstories:\n${stories}\n---\n\n${fixture.scriptText.trim()}\n`;
return [{json:{markdown,contentBase64:Buffer.from(markdown).toString('base64'),audioUrl}}];""",
        ),
        http_node(
            "github_main",
            "Read GitHub Main Ref",
            3360,
            {
                "url": "https://api.github.com/repos/anitguru/anit.guru/git/ref/heads/main",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"}, {"name": "X-GitHub-Api-Version", "value": "2022-11-28"}]},
                "options": {"timeout": 30000},
            },
            GITHUB_HTTP_CREDENTIAL,
            "HTTP exception: the installed GitHub node has no get-branch-ref operation.",
        ),
        code_node(
            "github_context",
            "Prepare GitHub Staging Branch",
            3600,
            r"""const main = $input.first().json;
const fixture = $('Portable Staging Context').first().json;
const content = $('Generate Episode Markdown').first().json;
if (!/^[a-f0-9]{40}$/.test(String(main.object?.sha || ''))) throw new Error('GitHub main SHA missing');
const branch = `podcast-shadow/portable-${fixture.date}-${fixture.sourceExecutionId}-${$execution.id}`;
const path = `content/podcast-shadow/${fixture.date}-${fixture.sourceExecutionId}-${$execution.id}.md`;
return [{json:{mainSha:main.object.sha,branch,path,contentBase64:content.contentBase64,markdown:content.markdown}}];""",
        ),
        http_node(
            "github_branch",
            "Create GitHub Staging Branch",
            3840,
            {
                "method": "POST",
                "url": "https://api.github.com/repos/anitguru/anit.guru/git/refs",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"}, {"name": "X-GitHub-Api-Version", "value": "2022-11-28"}]},
                "sendBody": True,
                "contentType": "json",
                "specifyBody": "json",
                "jsonBody": "={{ {ref:'refs/heads/' + $json.branch,sha:$json.mainSha} }}",
                "options": {"timeout": 30000},
            },
            GITHUB_HTTP_CREDENTIAL,
            "HTTP exception: the installed GitHub node has no create-branch-ref operation.",
        ),
        node(
            "github_commit",
            "GitHub - Create Episode File",
            "n8n-nodes-base.github",
            4080,
            {
                "resource": "file",
                "operation": "create",
                "owner": {"mode": "name", "value": "anitguru"},
                "repository": {"mode": "name", "value": "anit.guru"},
                "filePath": "={{ $('Prepare GitHub Staging Branch').first().json.path }}",
                "binaryData": False,
                "fileContent": "={{ $('Prepare GitHub Staging Branch').first().json.markdown }}",
                "commitMessage": "={{ 'stage: portable podcast ' + $('Portable Staging Context').first().json.date }}",
                "additionalParameters": {"branch": {"branch": "={{ $('Prepare GitHub Staging Branch').first().json.branch }}"}},
            },
            typeVersion=1.1,
            credentials=GITHUB_NATIVE_CREDENTIAL,
        ),
        node(
            "github_read_file",
            "GitHub - Get Episode File",
            "n8n-nodes-base.github",
            4320,
            {
                "resource": "file",
                "operation": "get",
                "owner": {"mode": "name", "value": "anitguru"},
                "repository": {"mode": "name", "value": "anit.guru"},
                "filePath": "={{ $('Prepare GitHub Staging Branch').first().json.path }}",
                "asBinaryProperty": False,
                "additionalParameters": {"reference": "={{ $('Prepare GitHub Staging Branch').first().json.branch }}"},
            },
            typeVersion=1.1,
            credentials=GITHUB_NATIVE_CREDENTIAL,
        ),
        code_node(
            "validate_github",
            "Validate GitHub Commit",
            4560,
            r"""const file = $input.first().json;
const expected = $('Prepare GitHub Staging Branch').first().json;
const commit = $('GitHub - Create Episode File').first().json;
const decoded = Buffer.from(String(file.content || '').replace(/\n/g,''),'base64').toString('utf8');
if (file.path !== expected.path || decoded !== expected.markdown) throw new Error('GitHub file readback mismatch');
if (!/^[a-f0-9]{40}$/.test(String(commit.commit?.sha || ''))) throw new Error('GitHub commit SHA missing');
return [{json:{branch:expected.branch,path:expected.path,commitSha:commit.commit.sha,contentSha:file.sha,verified:true}}];""",
        ),
        ledger_node(
            "ledger_github",
            "Ledger - GitHub Verified",
            4800,
            "github-staging",
            "passed",
            audio_sha256="={{ $('Portable Staging Context').first().json.audio.sha256 }}",
            artifact_urls_json="={{ JSON.stringify({audio:$('Validate Cloudinary Upload').first().json.secure_url,branch:$('Validate GitHub Commit').first().json.branch,path:$('Validate GitHub Commit').first().json.path,commit:$('Validate GitHub Commit').first().json.commitSha}) }}",
        ),
        code_node(
            "database_context",
            "Prepare Temporary Episode Row",
            5040,
            r"""const fixture = $('Portable Staging Context').first().json;
return [{json:{databaseRequestContext:{row:{episode:fixture.episode,date:fixture.date,audioUrl:$('Validate Cloudinary Upload').first().json.secure_url,audioLength:$('Validate Cloudinary Upload').first().json.bytes,duration:fixture.audio.duration,stories:fixture.selectedStories}}}}];""",
        ),
        node(
            "postgres_rollback",
            "Stage Episode Row then ROLLBACK",
            "n8n-nodes-base.postgres",
            5280,
            {
                "operation": "executeQuery",
                "query": "BEGIN;\nCREATE TEMP TABLE podcast_episodes_shadow (episode integer NOT NULL,date date NOT NULL,audio_url text NOT NULL,audio_length bigint NOT NULL,duration text NOT NULL,stories jsonb NOT NULL) ON COMMIT DROP;\nINSERT INTO podcast_episodes_shadow (episode,date,audio_url,audio_length,duration,stories) VALUES ($1,$2::date,$3,$4,$5,$6::jsonb);\nROLLBACK;\nSELECT $1::integer AS episode,$2::text AS date,$3::text AS \"audioUrl\",$4::bigint AS \"audioLength\",$5::text AS duration,jsonb_array_length($6::jsonb) AS \"storyCount\",true AS \"rolledBack\";",
                "options": {"queryReplacement": "={{ [ $json.databaseRequestContext.row.episode,$json.databaseRequestContext.row.date,$json.databaseRequestContext.row.audioUrl,$json.databaseRequestContext.row.audioLength,$json.databaseRequestContext.row.duration,JSON.stringify($json.databaseRequestContext.row.stories) ] }}"},
            },
            typeVersion=2.6,
            credentials=POSTGRES_CREDENTIAL,
        ),
        code_node(
            "validate_rollback",
            "Validate Episode Row ROLLBACK",
            5520,
            r"""const row = $input.first().json;
if (row.rolledBack !== true || Number(row.storyCount) !== 4) throw new Error('temporary episode row was not proven rolled back');
return [{json:row}];""",
        ),
        ledger_node("ledger_database", "Ledger - Database Shape Verified", 5760, "database-shape", "passed", audio_sha256="={{ $('Portable Staging Context').first().json.audio.sha256 }}"),
        code_node(
            "notification_context",
            "Prepare Staging Notification",
            6000,
            r"""const fixture = $('Portable Staging Context').first().json;
const git = $('Validate GitHub Commit').first().json;
return [{json:{text:`🧪 Portable n8n staging verified — ${fixture.portableRunId}; Cloudinary direct; GitHub ${git.commitSha.slice(0,12)}; DB rolled back.`}}];""",
        ),
        node(
            "telegram",
            "Send Staging Test Notification",
            "n8n-nodes-base.telegram",
            6240,
            {"resource": "message", "operation": "sendMessage", "chatId": "8100669692", "text": "={{ $json.text }}", "additionalFields": {"disable_notification": True}},
            typeVersion=1.2,
            credentials=TELEGRAM_CREDENTIAL,
        ),
        code_node(
            "validate_notification",
            "Validate Staging Notification",
            6480,
            r"""const sent = $input.first().json;
const messageId = sent.result?.message_id;
if (sent.ok !== true || !Number.isInteger(messageId) || messageId < 1) throw new Error('Telegram did not return a message ID');
return [{json:{messageId,verified:true}}];""",
        ),
        ledger_node(
            "ledger_complete",
            "Ledger - Staging Complete",
            6720,
            "staging-complete",
            "passed",
            audio_sha256="={{ $('Portable Staging Context').first().json.audio.sha256 }}",
            qa_json="={{ JSON.stringify({audio:$('Portable Staging Context').first().json.audio,srt:$('Portable Staging Context').first().json.srt.alignment}) }}",
            artifact_urls_json="={{ JSON.stringify({audio:$('Validate Cloudinary Upload').first().json.secure_url,github:$('Validate GitHub Commit').first().json}) }}",
        ),
        node("stop", "Portable Staging Stop", "n8n-nodes-base.noOp", 6960, {}, notes="Hard stop. No production branch, production table, scheduler, or media notification exists."),
        code_node(
            "return_contract", "Return Staging Distribution Contract", 7200,
            r"""const c=$('Portable Staging Context').first().json,u=$('Validate Cloudinary Upload').first().json,g=$('Validate GitHub Commit').first().json,n=$('Validate Staging Notification').first().json;
return [{json:{runMode:c.runMode,publishMode:'staging',date:c.date,runId:c.portableRunId,episode:c.episode,audio_sha256:c.audio.sha256,srt_sha256:c.srt.sha256,cloudinary:{publicId:u.public_id,secureUrl:u.secure_url,bytes:u.bytes},github:g,telegramMessageId:n.messageId,databaseRolledBack:true,distributionValidated:true}}];""",
        ),
    ]

    connections: dict = {}
    connect(connections, "Manual Portable Staging Trigger", "Portable Staging Context")
    connect(connections, "When Called by Parent Workflow", "Portable Staging Context")
    connect(connections, "Portable Staging Context", "Ledger - Staging Started")
    connect(connections, "Ledger - Staging Started", "Incoming Parent Audio?")
    connections["Incoming Parent Audio?"] = {
        "main": [
            [{"node": "Restore Incoming Audio Binary", "type": "main", "index": 0}],
            [{"node": "Download Verified Audio from Cloudinary", "type": "main", "index": 0}],
        ]
    }
    for source in ("Restore Incoming Audio Binary", "Download Verified Audio from Cloudinary"):
        connections[source] = {
            "main": [[
                {"node": "SHA256 Downloaded Audio", "type": "main", "index": 0},
                {"node": "Merge Audio + Verified Hash", "type": "main", "index": 0},
            ]]
        }
    connect(connections, "SHA256 Downloaded Audio", "Validate Downloaded Audio")
    connections["Validate Downloaded Audio"] = {
        "main": [[{"node": "Merge Audio + Verified Hash", "type": "main", "index": 1}]]
    }
    names = [n["name"] for n in nodes]
    start = names.index("Merge Audio + Verified Hash")
    for source, target in zip(names[start:], names[start + 1:]):
        connect(connections, source, target)

    workflow = {
        "id": WORKFLOW_ID,
        "name": WORKFLOW_NAME,
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "availableInMCP": True, "binaryMode": "separate"},
        "meta": {"templateCredsSetupCompleted": True},
        "pinData": {},
        "tags": [],
    }
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    forbidden = ["10.0.70.202", ":8787", "podcast-worker", "ssh"]
    for value in forbidden:
        if value in raw:
            raise ValueError(f"portable workflow contains forbidden value: {value}")
    if workflow["active"]:
        raise ValueError("staging workflow must be inactive")
    allowed_hosts = {
        "res.cloudinary.com",
        "api.cloudinary.com",
        "api.github.com",
    }
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            nonblank = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(nonblank) > 100:
                raise ValueError(f"Code node too large: {item['name']} ({len(nonblank)} lines)")
        if item["type"] == "n8n-nodes-base.httpRequest":
            if not item.get("notes", "").startswith("HTTP exception:"):
                raise ValueError(f"HTTP node lacks a documented built-in-node exception: {item['name']}")
            url = item["parameters"].get("url", "")
            if "10.0." in url:
                raise ValueError(f"portable staging HTTP node contains a private LXC address: {item['name']}")
            for host in [part for part in allowed_hosts if part in url]:
                break
            else:
                if not url.startswith("={{"):
                    raise ValueError(f"undeclared HTTP host in {item['name']}: {url}")


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
