#!/usr/bin/env python3
"""Build the explicit manual-production parent from the proven modular parent."""

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
        "manual": "Manual Production Replacement Trigger",
        "context": "Prepare Manual Production Context",
        "gate": "Hard Manual Production Authorization Gate",
        "ledger_start": "Ledger - Manual Production Started",
        "call_distribution": "Run Production Distribution Sub-workflow",
        "validate_distribution": "Validate Production Distribution Contract",
        "stop": "Manual Production Run Complete",
    }
    for node_id, name in names.items():
        rename(workflow, node_id, name)

    by_id = {n["id"]: n for n in workflow["nodes"]}
    by_id["context"]["parameters"]["jsCode"] = r"""const now=new Date();
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
return [{json:{runMode:'shadow',publishMode:'production',notifyMode:'production',manualProductionApproved:true,date,runId:`portable-production/${date}/${$execution.id}`,attempt:1}}];"""
    by_id["gate"]["parameters"]["jsCode"] = r"""const c=$input.first().json;const failures=[];
if(c.runMode!=='shadow')failures.push('generation mode');if(c.publishMode!=='production')failures.push('publish mode');if(c.notifyMode!=='production')failures.push('notify mode');if(c.manualProductionApproved!==true)failures.push('operator approval');
if(!/^portable-production\/\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]+$/.test(c.runId))failures.push('runId');if(failures.length)throw new Error(`manual production gate: ${failures.join(', ')}`);return [{json:c}];"""
    ledger = by_id["ledger_start"]["parameters"]["columns"]["value"]
    ledger["run_mode"] = "production-manual"
    ledger["stage"] = "production-parent-start"

    call = by_id["call_distribution"]
    call["parameters"]["workflowId"] = {"__rl": True, "value": "pPortableProdX8Q3M7", "mode": "list", "cachedResultName": "WF-podcast-portable-production-v1"}
    values = call["parameters"]["workflowInputs"]["value"]
    values["publishMode"] = "={{ $('Hard Manual Production Authorization Gate').first().json.publishMode }}"
    values["manualProductionApproved"] = "={{ $('Hard Manual Production Authorization Gate').first().json.manualProductionApproved }}"
    schema = call["parameters"]["workflowInputs"]["schema"]
    schema.append({"id": "manualProductionApproved", "displayName": "manualProductionApproved", "required": True, "defaultMatch": False, "display": True, "canBeUsedToMatch": True, "type": "boolean"})
    call["notes"] = "Calls the visible one-shot production workflow: native Cloudinary, GitHub/main, Supabase, Telegram MP3/SRT, readback gates, and ledger."

    by_id["validate_distribution"]["parameters"]["jsCode"] = r"""const r=$input.first().json;
if(r.distributionValidated!==true||r.publishMode!=='production'||r.supabasePersisted!==true)throw new Error('production distribution proof missing');
if(!String(r.cloudinary?.secureUrl||'').startsWith('https://res.cloudinary.com/')||!/^[a-f0-9]{40}$/.test(String(r.github?.commitSha||'')))throw new Error('production artifact readback missing');
if(!Array.isArray(r.telegramMessageIds)||r.telegramMessageIds.length!==3)throw new Error('production notification proof missing');return [{json:r}];"""
    by_id["stop"]["notes"] = "Manual production terminal node. No schedule exists in this workflow."
    workflow["active"] = False
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "scheduletrigger"):
        if forbidden in raw:
            raise ValueError(f"production parent contains forbidden value: {forbidden}")
    if workflow["active"] or len([n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]) != 5:
        raise ValueError("production parent must be inactive with five visible sub-workflow calls")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
