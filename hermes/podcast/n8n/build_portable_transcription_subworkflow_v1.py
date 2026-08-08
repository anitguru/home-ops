#!/usr/bin/env python3
"""Build the portable Whisper transcription and authored-text SRT sub-workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "run37-portable-staging-context.json"
OUTPUT = HERE / "wf-podcast-sub-transcription-v1.json"
WORKFLOW_ID = "pTransSubX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-transcription-v1"
WHISPER_URL = "https://whisper.transformers.lan/v1/audio/transcriptions"
FIXTURE_AUDIO_URL = "https://res.cloudinary.com/ddicetqs5/video/upload/v1786220477/anitguru-shadow/gurus-tech-bytes-2026-08-08-37.mp3"


def node(node_id: str, name: str, node_type: str, x: int, y: int, parameters: dict, **extra: object) -> dict:
    result = {"id": node_id, "name": name, "type": node_type, "typeVersion": extra.pop("typeVersion", 1), "position": [x, y], "parameters": parameters}
    result.update(extra)
    return result


def code(node_id: str, name: str, x: int, y: int, js: str, notes: str = "") -> dict:
    return node(node_id, name, "n8n-nodes-base.code", x, y, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js.strip()}, typeVersion=2, notes=notes)


def connect(connections: dict, source: str, target: str, target_input: int = 0) -> None:
    connections.setdefault(source, {"main": [[]]})["main"][0].append({"node": target, "type": "main", "index": target_input})


def build() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    manual = {
        "runMode": "shadow", "date": fixture["date"], "runId": "transcription-fixture/run37", "episode": fixture["episode"],
        "selectedStories": fixture["selectedStories"], "scriptText": fixture["scriptText"],
        "script_sha256": hashlib.sha256(fixture["scriptText"].encode()).hexdigest(),
        "audio_sha256": fixture["audio"]["sha256"], "audioQa": {"duration_seconds": fixture["audio"]["durationSeconds"]}, "mediaValidated": True,
    }
    nodes = [
        node("manual", "Manual Transcription Test Trigger", "n8n-nodes-base.manualTrigger", 0, -180, {}),
        node("sub_trigger", "When Called by Parent Workflow", "n8n-nodes-base.executeWorkflowTrigger", 0, 80, {"inputSource": "jsonExample", "jsonExample": json.dumps({"runMode": "shadow", "date": "2026-08-08", "runId": "portable-shadow/example", "episode": 125, "selectedStories": [], "scriptText": "approved authored text", "script_sha256": "0" * 64, "audio_sha256": "0" * 64, "audioQa": {"duration_seconds": 120}, "mediaValidated": True}, indent=2)}, typeVersion=1.2),
        code("fixture", "Prepare Transcription Fixture Context", 240, -260, "return [{json:" + json.dumps(manual, separators=(",", ":")) + "}];"),
        node(
            "fixture_audio", "Download Verified Fixture Audio", "n8n-nodes-base.httpRequest", 240, -100,
            {"url": FIXTURE_AUDIO_URL, "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "audio"}}, "timeout": 120000}},
            typeVersion=4.4, notes="HTTP exception: the verified Cloudinary node supports upload/transform operations but not downloading an existing delivery URL for this manual fixture branch.",
        ),
        node("fixture_merge", "Merge Fixture Context + Audio", "n8n-nodes-base.merge", 480, -180, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        code(
            "validate_input", "Validate Transcription Input", 720, 0,
            r"""const i=$input.first();const r=i.json;const failures=[];
if(r.runMode!=='shadow'||r.mediaValidated!==true) failures.push('mode/media proof');
if(!/^[a-f0-9]{64}$/.test(String(r.script_sha256||''))||!/^[a-f0-9]{64}$/.test(String(r.audio_sha256||''))) failures.push('hashes');
if(!i.binary?.audio) failures.push('audio binary');
if(String(r.scriptText||'').split(/\n\s*\n/).filter(Boolean).length!==6) failures.push('six paragraphs');
if(failures.length) throw new Error(`transcription input: ${failures.join(', ')}`);
return [{json:r,binary:{audio:i.binary.audio}}];""",
        ),
        node(
            "whisper", "Whisper - Verbose Word Timestamps", "n8n-nodes-base.httpRequest", 960, 0,
            {
                "method": "POST", "url": WHISPER_URL, "sendBody": True, "contentType": "multipart-form-data",
                "bodyParameters": {"parameters": [
                    {"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "audio"},
                    {"name": "response_format", "value": "verbose_json"}, {"name": "language", "value": "en"},
                    {"name": "timestamp_granularities[]", "value": "word"},
                ]},
                "options": {"allowUnauthorizedCerts": True, "timeout": 300000},
            },
            typeVersion=4.4, notes="HTTP exception: the self-hosted whisper.cpp service has no native n8n node; verbose segment/word timestamps are required for authored-text alignment.",
        ),
        code(
            "normalize", "Normalize Authored + Whisper Words", 1200, 0,
            r"""const w=$input.first().json;const c=$('Validate Transcription Input').first().json;
const norm=s=>String(s).toLowerCase().replace(/['’]/g,' ').match(/[a-z0-9]+/g)||[];
const heard=(w.segments||[]).flatMap(s=>(s.words||[]).flatMap(x=>norm(x.word).map(word=>({word,start:Number(x.start),end:Number(x.end)}))));
const raw=String(c.scriptText).split(/\s+/).filter(Boolean);const reference=[];const display=[];
for(const text of raw){const parts=norm(text);if(!parts.length) continue;const start=reference.length;reference.push(...parts);display.push({text,start,end:reference.length-1});}
if(!heard.length||!reference.length) throw new Error('Whisper/reference words missing');
return [{json:{...c,whisperText:w.text,whisperDuration:Number(w.duration),heard,reference,display}}];""",
        ),
        code(
            "align", "Align Authored Words to Whisper", 1440, 0,
            r"""const r=$input.first().json,a=r.reference,b=r.heard.map(x=>x.word),n=a.length,m=b.length;
const d=Array.from({length:n+1},()=>new Uint16Array(m+1));
for(let i=1;i<=n;i++) for(let j=1;j<=m;j++) d[i][j]=a[i-1]===b[j-1]?d[i-1][j-1]+1:Math.max(d[i-1][j],d[i][j-1]);
const anchors=[];let i=n,j=m;while(i&&j){if(a[i-1]===b[j-1]){anchors.push({r:i-1,h:j-1});i--;j--;}else if(d[i-1][j]>=d[i][j-1])i--;else j--;};anchors.reverse();
if(!anchors.length) throw new Error('no exact transcription anchors');
const times=Array(n);for(const x of anchors) times[x.r]={start:r.heard[x.h].start,end:r.heard[x.h].end,exact:true};
const points=[{r:-1,t:0},...anchors.map(x=>({r:x.r,t:r.heard[x.h].start})),{r:n,t:r.whisperDuration}];
for(let p=0;p<points.length-1;p++){const l=points[p],q=points[p+1],span=q.r-l.r;for(let k=l.r+1;k<q.r;k++){const t=l.t+(q.t-l.t)*(k-l.r)/span;times[k]={start:t,end:t+0.12,exact:false};}}
for(let k=0;k<n;k++){if(!times[k]) continue;times[k].start=Math.max(0,times[k].start);times[k].end=Math.max(times[k].start+0.04,times[k].end);}
return [{json:{...r,anchors,times,exactAnchorRatio:anchors.length/n}}];""",
        ),
        code(
            "srt", "Build Authored Text SRT Cues", 1680, 0,
            r"""const r=$input.first().json,fmt=x=>{x=Math.max(0,x);const h=Math.floor(x/3600),m=Math.floor(x%3600/60),s=Math.floor(x%60),ms=Math.round((x-Math.floor(x))*1000);return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`};
const wrap=ws=>{let a='',b='';for(const w of ws){if((a+' '+w).trim().length<=47)a=(a+' '+w).trim();else b=(b+' '+w).trim();}return b?[a,b]:[a];};
const cues=[];let words=[];const flush=()=>{if(!words.length)return;const first=words[0],last=words[words.length-1],lines=wrap(words.map(x=>x.text));cues.push({start:r.times[first.start].start,end:r.times[last.end].end,lines});words=[];};
for(const w of r.display){const trial=[...words,w],lines=wrap(trial.map(x=>x.text));if(words.length&&(lines.length>2||lines.some(x=>x.length>47)))flush();words.push(w);if(/[.!?][\"']?$/.test(w.text)&&words.length>=5)flush();}flush();
const srtText=cues.map((c,i)=>`${i+1}\n${fmt(c.start)} --> ${fmt(c.end)}\n${c.lines.join('\n')}\n`).join('\n');
return [{json:{...r,cues,srtText,cueCount:cues.length,maximumLineCharacters:Math.max(...cues.flatMap(c=>c.lines.map(x=>x.length))),maximumLinesPerCue:Math.max(...cues.map(c=>c.lines.length))}}];""",
        ),
        node("to_file", "Convert SRT Text to File", "n8n-nodes-base.convertToFile", 1920, 120, {"operation": "toText", "sourceProperty": "srtText", "binaryPropertyName": "srt", "options": {"encoding": "utf8", "fileName": "={{ `gurus-tech-bytes-${$('Validate Transcription Input').first().json.date}.srt` }}"}}, typeVersion=1.1),
        node("srt_hash", "SHA256 SRT File", "n8n-nodes-base.crypto", 2160, 120, {"action": "hash", "binaryData": True, "binaryPropertyName": "srt", "type": "SHA256", "dataPropertyName": "srt_sha256", "encoding": "hex"}, typeVersion=2),
        node("merge_srt", "Merge SRT Contract + File Hash", "n8n-nodes-base.merge", 2400, 0, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        code(
            "qa", "Measure Transcript Alignment QA", 2640, 0,
            r"""const i=$input.first(),r=i.json,a=r.reference,b=r.heard.map(x=>x.word);let prev=Array.from({length:b.length+1},(_,j)=>j);
for(let x=1;x<=a.length;x++){const cur=[x];for(let y=1;y<=b.length;y++)cur[y]=a[x-1]===b[y-1]?prev[y-1]:1+Math.min(prev[y-1],prev[y],cur[y-1]);prev=cur;}
const thirds=['beginning','middle','end'].map((name,k)=>{const lo=Math.floor(a.length*k/3),hi=Math.floor(a.length*(k+1)/3)-1,found=r.anchors.filter(x=>x.r>=lo&&x.r<=hi);return {name,referenceWordStart:lo+1,referenceWordEnd:hi+1,startSeconds:r.times[lo].start,endSeconds:r.times[hi].end,exactAnchors:found.length};});
let maxGap=0,last=-1;for(const x of r.anchors){maxGap=Math.max(maxGap,x.r-last-1);last=x.r;}maxGap=Math.max(maxGap,a.length-last-1);
const alignment={durationSeconds:r.whisperDuration,referenceWords:a.length,transcriptWords:b.length,wordErrorRate:Number((prev[b.length]/a.length).toFixed(6)),exactAnchors:r.anchors.length,exactAnchorRatio:Number(r.exactAnchorRatio.toFixed(6)),cueCount:r.cueCount,maximumLineCharacters:r.maximumLineCharacters,maximumLinesPerCue:r.maximumLinesPerCue,thirds,maximumUnanchoredRunWords:maxGap};
const srt=$('Convert SRT Text to File').first().binary?.srt;if(!srt) throw new Error('native SRT file binary missing');
return [{json:{runMode:r.runMode,date:r.date,runId:r.runId,episode:r.episode,selectedStories:r.selectedStories,scriptText:r.scriptText,script_sha256:r.script_sha256,audio_sha256:r.audio_sha256,audioQa:r.audioQa,srt_sha256:r.srt_sha256,alignment,transcriptionValidated:true},binary:{srt}}];""",
        ),
        code(
            "gate", "Hard Transcript + SRT Quality Gate", 2880, 0,
            r"""const i=$input.first(),r=i.json,a=r.alignment,fail=[];
if(!/^[a-f0-9]{64}$/.test(String(r.srt_sha256||''))) fail.push('SRT hash');
if(a.wordErrorRate>0.20||a.exactAnchorRatio<0.60) fail.push('WER/anchors');
if(a.maximumLineCharacters>47||a.maximumLinesPerCue>2||a.cueCount<6) fail.push('cue layout');
if(a.thirds?.map(x=>x.name).join(',')!=='beginning,middle,end'||a.thirds.some(x=>x.exactAnchors<1)) fail.push('third anchors');
if(a.maximumUnanchoredRunWords>20) fail.push('unanchored run');
if(fail.length) throw new Error(`transcription gate: ${fail.join(', ')}`);
return [i];""",
        ),
        node(
            "ledger", "Ledger - Transcription QA Passed", "n8n-nodes-base.dataTable", 3120, 0,
            {"resource": "row", "operation": "insert", "dataTableId": {"mode": "name", "value": "podcast_run_ledger"}, "columns": {"mappingMode": "defineBelow", "value": {"run_id": "={{ $json.runId }}", "execution_id": "={{ $execution.id }}", "run_mode": "shadow", "episode": "={{ $json.episode }}", "episode_date": "={{ $json.date }}", "stage": "transcription-qa", "status": "passed", "attempt": 1, "selected_stories_json": "={{ JSON.stringify($json.selectedStories) }}", "script_sha256": "={{ $json.script_sha256 }}", "audio_sha256": "={{ $json.audio_sha256 }}", "srt_sha256": "={{ $json.srt_sha256 }}", "qa_json": "={{ JSON.stringify({audio:$json.audioQa,alignment:$json.alignment}) }}", "artifact_urls_json": "", "error": "", "started_at": "={{ $now.toISO() }}", "updated_at": "={{ $now.toISO() }}"}}, "options": {}}, typeVersion=1.1,
        ),
        node("merge_binary", "Merge Audio + SRT Binaries", "n8n-nodes-base.merge", 3120, 180, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        node("merge_final", "Merge Binaries + Transcription Ledger", "n8n-nodes-base.merge", 3360, 0, {"mode": "combine", "combineBy": "combineByPosition", "options": {}}, typeVersion=3.2),
        code(
            "return_contract", "Return Clean Transcription Contract", 3600, 0,
            r"""const i=$input.first();
if(!i.binary?.audio||!i.binary?.srt) throw new Error('audio/SRT binaries missing at transcription boundary');
return [{json:{runMode:i.json.runMode,date:i.json.date||i.json.episode_date,runId:i.json.runId||i.json.run_id,episode:i.json.episode,selectedStories:i.json.selectedStories,scriptText:i.json.scriptText,script_sha256:i.json.script_sha256,audio_sha256:i.json.audio_sha256,audioQa:i.json.audioQa,srt_sha256:i.json.srt_sha256,alignment:i.json.alignment,transcriptionValidated:true},binary:{audio:i.binary.audio,srt:i.binary.srt}}];""",
            notes="Reusable boundary returns only the assembled audio and authored SRT binaries plus their verified hashes/QA contract.",
        ),
    ]

    connections: dict = {}
    connect(connections, "Manual Transcription Test Trigger", "Prepare Transcription Fixture Context")
    connect(connections, "Manual Transcription Test Trigger", "Download Verified Fixture Audio")
    connect(connections, "Prepare Transcription Fixture Context", "Merge Fixture Context + Audio", 0)
    connect(connections, "Download Verified Fixture Audio", "Merge Fixture Context + Audio", 1)
    connect(connections, "Merge Fixture Context + Audio", "Validate Transcription Input")
    connect(connections, "When Called by Parent Workflow", "Validate Transcription Input")
    connect(connections, "Validate Transcription Input", "Whisper - Verbose Word Timestamps")
    connect(connections, "Validate Transcription Input", "Merge Audio + SRT Binaries", 0)
    for source, target in [("Whisper - Verbose Word Timestamps", "Normalize Authored + Whisper Words"), ("Normalize Authored + Whisper Words", "Align Authored Words to Whisper"), ("Align Authored Words to Whisper", "Build Authored Text SRT Cues")]:
        connect(connections, source, target)
    connect(connections, "Build Authored Text SRT Cues", "Convert SRT Text to File")
    connect(connections, "Build Authored Text SRT Cues", "Merge SRT Contract + File Hash", 0)
    connect(connections, "Convert SRT Text to File", "SHA256 SRT File")
    connect(connections, "SHA256 SRT File", "Merge SRT Contract + File Hash", 1)
    connect(connections, "Merge SRT Contract + File Hash", "Measure Transcript Alignment QA")
    connect(connections, "Measure Transcript Alignment QA", "Hard Transcript + SRT Quality Gate")
    connect(connections, "Measure Transcript Alignment QA", "Merge Audio + SRT Binaries", 1)
    connect(connections, "Hard Transcript + SRT Quality Gate", "Ledger - Transcription QA Passed")
    connect(connections, "Merge Audio + SRT Binaries", "Merge Binaries + Transcription Ledger", 0)
    connect(connections, "Ledger - Transcription QA Passed", "Merge Binaries + Transcription Ledger", 1)
    connect(connections, "Merge Binaries + Transcription Ledger", "Return Clean Transcription Contract")

    workflow = {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": True, "binaryMode": "separate"}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh"):
        if forbidden in raw:
            raise ValueError(f"transcription workflow contains forbidden value: {forbidden}")
    http_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    if len(http_nodes) != 2 or any(not n.get("notes", "").startswith("HTTP exception:") for n in http_nodes):
        raise ValueError("fixture download and Whisper HTTP exceptions must both be visible/documented")
    if not any(n["type"] == "n8n-nodes-base.convertToFile" for n in workflow["nodes"]):
        raise ValueError("native Convert to File node missing")
    for item in workflow["nodes"]:
        if item["type"] == "n8n-nodes-base.code":
            lines = [line for line in item["parameters"]["jsCode"].splitlines() if line.strip()]
            if len(lines) > 22:
                raise ValueError(f"transcription Code node too large: {item['name']} ({len(lines)} lines)")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
