#!/usr/bin/env python3
"""Build the scheduled production parent from the proven modular parent."""

from __future__ import annotations

import json
from pathlib import Path

import build_portable_parent_shadow_v1 as shadow


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-portable-production-parent-v1.json"


def rename(workflow: dict, node_id: str, new_name: str) -> None:
    target = next(n for n in workflow["nodes"] if n["id"] == node_id)
    old = target["name"]
    target["name"] = new_name
    if old in workflow["connections"]:
        workflow["connections"][new_name] = workflow["connections"].pop(old)
    for outputs in workflow["connections"].values():
        for branch in outputs.get("main", []):
            for edge in branch:
                if edge["node"] == old:
                    edge["node"] = new_name
    def replace_references(value):
        if isinstance(value, str):
            return value.replace(old, new_name)
        if isinstance(value, list):
            return [replace_references(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_references(item) for key, item in value.items()}
        return value
    workflow["nodes"] = replace_references(workflow["nodes"])


def build() -> dict:
    workflow = shadow.build()
    workflow["id"] = "pPortableProdParentX8"
    workflow["name"] = "WF-podcast-portable-production-parent-v1"

    names = {
        "manual": "Manual Production Trigger",
        "context": "Prepare Production Context",
        "gate": "Hard Production Authorization Gate",
        "ledger_start": "Ledger - Production Started",
        "call_distribution": "Run Production Distribution Sub-workflow",
        "validate_distribution": "Validate Production Distribution Contract",
        "stop": "Production Run Complete",
    }
    for node_id, name in names.items():
        rename(workflow, node_id, name)

    by_id = {n["id"]: n for n in workflow["nodes"]}
    schedule_name = "Daily Production Schedule — 06:00 ET"
    workflow["nodes"].append(
        shadow.node(
            "production_schedule",
            schedule_name,
            "n8n-nodes-base.scheduleTrigger",
            0,
            {"rule": {"interval": [{"triggerAtHour": 6, "triggerAtMinute": 0}]}},
            typeVersion=1.2,
            position=[0, 180],
            notes="Sole scheduled producer after cutover. Runs daily at 06:00 America/New_York.",
        )
    )
    workflow["connections"][schedule_name] = {
        "main": [[{"node": names["context"], "type": "main", "index": 0}]]
    }
    by_id["context"]["parameters"]["jsCode"] = r"""const now=new Date();
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
return [{json:{runMode:'production',publishMode:'production',notifyMode:'production',manualProductionApproved:true,date,runId:`portable-production/${date}/${$execution.id}`,attempt:1}}];"""
    by_id["gate"]["parameters"]["jsCode"] = r"""const c=$input.first().json;const failures=[];
if(c.runMode!=='production')failures.push('generation mode');if(c.publishMode!=='production')failures.push('publish mode');if(c.notifyMode!=='production')failures.push('notify mode');if(c.manualProductionApproved!==true)failures.push('cutover authorization');
if(!/^portable-production\/\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]+$/.test(c.runId))failures.push('runId');if(failures.length)throw new Error(`production gate: ${failures.join(', ')}`);return [{json:c}];"""
    ledger = by_id["ledger_start"]["parameters"]["columns"]["value"]
    ledger["run_mode"] = "production"
    ledger["stage"] = "production-parent-start"

    call = by_id["call_distribution"]
    call["parameters"]["workflowId"] = {"__rl": True, "value": "pPortableProdX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-portable-production-v1"}
    values = call["parameters"]["workflowInputs"]["value"]
    values["publishMode"] = "={{ $('Hard Production Authorization Gate').first().json.publishMode }}"
    values["manualProductionApproved"] = "={{ $('Hard Production Authorization Gate').first().json.manualProductionApproved }}"
    schema = call["parameters"]["workflowInputs"]["schema"]
    schema.append({"id": "manualProductionApproved", "displayName": "manualProductionApproved", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "boolean"})
    call["notes"] = "Calls the visible one-shot production workflow: native Cloudinary, GitHub/main, Supabase, Telegram MP3/SRT, readback gates, and ledger."

    by_id["validate_distribution"]["parameters"]["jsCode"] = r"""const r=$input.first().json;
if(r.distributionValidated!==true||r.publishMode!=='production'||r.supabasePersisted!==true)throw new Error('production distribution proof missing');
if(!String(r.cloudinary?.secureUrl||'').startsWith('https://res.cloudinary.com/')||!/^[a-f0-9]{40}$/.test(String(r.github?.commitSha||'')))throw new Error('production artifact readback missing');
if(!Array.isArray(r.telegramMessageIds)||r.telegramMessageIds.length!==3)throw new Error('production notification proof missing');return [{json:r}];"""
    by_id["validate_intake"]["parameters"]["jsCode"] = by_id["validate_intake"]["parameters"]["jsCode"].replace("r.runMode!=='shadow'", "r.runMode!=='production'")
    by_id["stop"]["notes"] = "Scheduled/manual production terminal node after all distribution readbacks pass."
    workflow["settings"]["timezone"] = "America/New_York"
    workflow["settings"]["errorWorkflow"] = "k5nmdOyJm5znKQzK"
    workflow["settings"]["executionTimeout"] = 3600
    workflow["settings"]["saveExecutionProgress"] = True
    workflow["active"] = True
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh"):
        if forbidden in raw:
            raise ValueError(f"production parent contains forbidden value: {forbidden}")
    schedules = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    if not workflow["active"] or len(schedules) != 1 or schedules[0].get("disabled"):
        raise ValueError("production parent must contain one enabled schedule trigger")
    if len([n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]) != 5:
        raise ValueError("production parent must retain five visible sub-workflow calls")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
