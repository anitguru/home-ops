#!/usr/bin/env python3
"""Build exact visible audio+timestamp repair workflows for episodes 123 and 124."""

from __future__ import annotations

import json
from pathlib import Path

import build_friday_audio_repair_20260809 as base


HERE = Path(__file__).resolve().parent
TRANSCRIPTION_ID = "pTransSubX8Q3M7"

REPAIRS = {
    123: {
        "date": "2026-08-06",
        "day": "Thursday",
        "old_url": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786010527/anitguru/gurus-tech-bytes-2026-08-06.mp3",
        "public_id": "anitguru/gurus-tech-bytes-2026-08-06-rerender-v2",
        "numeric_greeting": "This is Guru's Tech Bytes, episode 123.",
        "spoken_greeting": "This is Guru's Tech Bytes, episode one hundred twenty three.",
    },
    124: {
        "date": "2026-08-07",
        "day": "Friday",
        "old_url": "https://res.cloudinary.com/ddicetqs5/video/upload/v1786286197/anitguru/gurus-tech-bytes-2026-08-07-rerender.mp3",
        "public_id": "anitguru/gurus-tech-bytes-2026-08-07-rerender-v2",
        "numeric_greeting": "This is Guru's Tech Bytes, episode 124.",
        "spoken_greeting": "This is Guru's Tech Bytes, episode one hundred twenty four.",
    },
}


def replace_strings(value, replacements):
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {replace_strings(key, replacements): replace_strings(item, replacements) for key, item in value.items()}
    return value


def transcription_call(label: str, x: int) -> dict:
    fields = ("runMode", "date", "runId", "episode", "selectedStories", "scriptText", "script_sha256", "audio_sha256", "audioQa", "mediaValidated")
    schema = [{
        "id": field,
        "displayName": field,
        "required": True,
        "defaultMatch": False,
        "display": True,
        "canBeUsedToMatch": True,
        "type": "array" if field == "selectedStories" else "number" if field == "episode" else "boolean" if field == "mediaValidated" else "object" if field == "audioQa" else "string",
    } for field in fields]
    return base.node(
        "transcription",
        f"Run Published Transcription + SRT for {label}",
        "n8n-nodes-base.executeWorkflow",
        x,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": TRANSCRIPTION_ID, "mode": "list", "cachedResultName": "WF-podcast-sub-transcription-v1"},
            "workflowInputs": {
                "mappingMode": "defineBelow",
                "value": {field: "={{ Number($json.episode) }}" if field == "episode" else f"={{{{ $json.{field} }}}}" for field in fields},
                "matchingColumns": [],
                "schema": schema,
                "attemptToConvertTypes": False,
                "convertFieldsToString": False,
            },
            "mode": "once",
            "options": {"waitForSubWorkflow": True},
        },
        typeVersion=1.3,
        notes="Visible reusable timestamp path: direct Whisper, authored-word alignment, SRT file/hash, and hard QA gate.",
    )


def build(episode: int) -> dict:
    cfg = REPAIRS[episode]
    replacements = [
        ("Friday", f"Episode {episode}"),
        ("friday", f"episode-{episode}"),
        ("2026-08-07", cfg["date"]),
        ("v1786096920", "v" + cfg["old_url"].split("/v", 1)[1].split("/", 1)[0]),
    ]
    if episode == 123:
        replacements.append(("124", "123"))
    workflow = replace_strings(base.build(), replacements)
    label = f"Episode {episode}"
    context_name = f"{label} Repair Context"
    parse_name = f"Recover {label} Transcript + Steer Episode Number"
    validate_media_name = f"Validate {label} Audio QA + Binary"
    upload_name = f"Cloudinary - Upload {label} Corrected Audio"
    workflow.update({
        "id": f"pEpisode{episode}RepairX8",
        "name": f"WF-podcast-episode-{episode}-audio-timestamp-repair-2026-08-09",
        "active": False,
    })
    by_id = {item["id"]: item for item in workflow["nodes"]}
    context = {
        "approved": True,
        "date": cfg["date"],
        "episode": episode,
        "runMode": "production",
        "runId": f"audio-timestamp-repair/{cfg['date']}/{episode}",
        "githubPath": f"content/podcast/{cfg['date']}.md",
        "oldAudioUrl": cfg["old_url"],
        "newCloudinaryPublicId": cfg["public_id"],
    }
    by_id["context"]["parameters"]["jsCode"] = "return [{json:" + json.dumps(context, separators=(",", ":")) + "}];"
    by_id["gate"]["parameters"]["jsCode"] = f"""const c=$input.first().json;
if(c.approved!==true||c.date!=='{cfg['date']}'||c.episode!=={episode}||c.runMode!=='production')throw new Error('{label} repair target mismatch');
if(c.githubPath!=='content/podcast/{cfg['date']}.md'||c.newCloudinaryPublicId!=='{cfg['public_id']}')throw new Error('{label} artifact target mismatch');return [{{json:c}}];"""
    replace_line = "const scriptText=body;"
    if episode == 123:
        replace_line = f"const scriptText=body.replace({json.dumps(cfg['numeric_greeting'])},{json.dumps(cfg['spoken_greeting'])});"
    by_id["parse"]["parameters"]["jsCode"] = f"""const f=$input.first().json,c=$('{context_name}').first().json;
const raw=Buffer.from(String(f.content||'').replace(/\\n/g,''),'base64').toString('utf8');const parts=raw.split(/^---\\s*$/m);const body=(parts.slice(2).join('---')).trim();
if(f.path!==c.githubPath||!raw.includes('episode: {episode}')||!raw.includes(c.oldAudioUrl)||!body.startsWith(\"Good morning, it's {cfg['day']}.\"))throw new Error('{label} GitHub source mismatch');
{replace_line}
if(!scriptText.includes({json.dumps(cfg['spoken_greeting'])})||scriptText.split(/\\n\\s*\\n/).length!==6||/\\d/.test(scriptText.split(/\\n\\s*\\n/)[0]))throw new Error('{label} spoken-number steering failed');return [{{json:{{...c,rawMarkdown:raw,scriptText,githubSourceSha:f.sha}}}}];"""
    by_id["upload"]["parameters"]["additionalFieldsFile"] = {
        "folder": "anitguru",
        "public_id": f"gurus-tech-bytes-{cfg['date']}-rerender-v2",
        "tags": f"podcast-production,episode-{episode}-corrected",
    }
    by_id["github_edit"]["parameters"]["commitMessage"] = f"podcast: repair episode {episode} spoken greeting, audio, and timestamps"
    by_id["ledger"]["parameters"]["columns"]["value"]["run_id"] = context["runId"]
    by_id["ledger"]["parameters"]["columns"]["value"]["stage"] = "audio-timestamp-link-replaced"
    by_id["media"]["retryOnFail"] = True
    by_id["media"]["maxTries"] = 2
    by_id["media"]["waitBetweenTries"] = 1000
    by_id["github_readback"]["retryOnFail"] = True
    by_id["github_readback"]["maxTries"] = 4
    by_id["github_readback"]["waitBetweenTries"] = 2000

    trans = transcription_call(label, 2280)
    validate_trans = base.code_node("validate_transcription", f"Validate {label} Timestamp QA + Binaries", 2340, r"""const i=$input.first(),r=i.json,a=r.alignment||{};
if(r.transcriptionValidated!==true||!i.binary?.audio||!i.binary?.srt)throw new Error('repair transcription binaries/proof missing');
if(!/^[a-f0-9]{64}$/.test(String(r.srt_sha256||''))||a.wordErrorRate>0.20||a.exactAnchorRatio<0.60||a.maximumLineCharacters>47||a.maximumLinesPerCue>2)throw new Error('repair timestamp QA invalid');return [i];""")
    github_wait = base.node("github_wait", f"Wait for {label} GitHub Consistency", "n8n-nodes-base.wait", 3960, {"resume": "timeInterval", "amount": 5, "unit": "seconds"}, typeVersion=1.1, notes="Visible consistency delay before native GitHub readback; avoids accepting stale pre-commit contents.")
    workflow["nodes"].extend([trans, validate_trans, github_wait])
    base.connect(workflow["connections"], validate_media_name, trans["name"])
    base.connect(workflow["connections"], trans["name"], validate_trans["name"])
    base.connect(workflow["connections"], validate_trans["name"], upload_name)
    base.connect(workflow["connections"], f"GitHub - Edit {label} Episode on Main", github_wait["name"])
    base.connect(workflow["connections"], github_wait["name"], f"GitHub - Read Back {label} Repair")
    by_id["hard_gate"]["parameters"]["jsCode"] = f"""const r=$input.first().json,c=$('{context_name}').first().json,u=$('Validate {label} Cloudinary Replacement').first().json,g=$('Validate {label} GitHub Readback').first().json,h=$('Validate {label} Download Hash').first().json,m=$('{validate_media_name}').first().json,t=$('{validate_trans['name']}').first().json;
if(r.date!==c.date||Number(r.episode)!==c.episode||r.audio_url!==u.secure_url||Number(r.duration_secs)!==Math.round(m.audioQa.duration_seconds)||g.verified!==true||h.verified!==true||t.transcriptionValidated!==true)throw new Error('{label} three-system/timestamp repair proof failed');return [{{json:{{repairValidated:true,date:c.date,episode:c.episode,oldAudioUrl:c.oldAudioUrl,newAudioUrl:u.secure_url,bytes:u.bytes,durationSeconds:m.audioQa.duration_seconds,audioQa:m.audioQa,audio_sha256:h.audio_sha256,srt_sha256:t.srt_sha256,alignment:t.alignment,github:g,supabase:r}}}}];"""
    ledger_values = by_id["ledger"]["parameters"]["columns"]["value"]
    ledger_values["srt_sha256"] = "={{ $json.srt_sha256 }}"
    ledger_values["qa_json"] = "={{ JSON.stringify({audioQa:$json.audioQa,alignment:$json.alignment}) }}"
    validate(workflow, episode)
    return workflow


def validate(workflow: dict, episode: int) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger"):
        if forbidden in raw:
            raise ValueError(f"episode {episode} repair contains forbidden value: {forbidden}")
    if workflow["active"] or len(workflow["nodes"]) != 28:
        raise ValueError(f"episode {episode} repair must be inactive and exactly 28 nodes")
    names = {item["name"] for item in workflow["nodes"]}
    targets = {edge["node"] for outputs in workflow["connections"].values() for branch in outputs.get("main", []) for edge in branch}
    if set(workflow["connections"]) - names or targets - names:
        raise ValueError(f"episode {episode} repair has broken connections")
    if sum(item["type"] == "n8n-nodes-base.httpRequest" for item in workflow["nodes"]) != 1:
        raise ValueError(f"episode {episode} repair must retain only the documented Cloudinary download HTTP exception")


if __name__ == "__main__":
    for number in sorted(REPAIRS):
        output = HERE / f"wf-podcast-episode-{number}-audio-timestamp-repair-2026-08-09.json"
        output.write_text(json.dumps(build(number), indent=2) + "\n")
        print(output)
