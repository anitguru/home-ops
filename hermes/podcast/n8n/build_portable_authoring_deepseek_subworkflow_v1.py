#!/usr/bin/env python3
"""Build the DeepSeek-V4-Flash-0731 authoring candidate from the proven GLM graph."""

from __future__ import annotations

import json
from pathlib import Path

import build_portable_authoring_subworkflow_v1 as glm


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-sub-authoring-deepseek-v1.json"
WORKFLOW_ID = "pAuthorDSX8Q3M7"
WORKFLOW_NAME = "WF-podcast-sub-authoring-deepseek-v1"
MODEL = "deepseek-v4-flash:0731-cloud"


def replace_strings(value):
    if isinstance(value, str):
        return value.replace("GLM-5.2", "DeepSeek V4 Flash 0731").replace("glm-5.2", MODEL)
    if isinstance(value, list):
        return [replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {replace_strings(key): replace_strings(item) for key, item in value.items()}
    return value


def build() -> dict:
    workflow = replace_strings(glm.build())
    workflow["id"] = WORKFLOW_ID
    workflow["name"] = WORKFLOW_NAME
    for node in workflow["nodes"]:
        if node["type"] == "@n8n/n8n-nodes-langchain.lmChatOllama":
            node["parameters"]["model"] = MODEL
        if node["id"] == "ledger":
            node["parameters"]["columns"]["value"]["stage"] = "authoring-deepseek-approved"
    workflow["active"] = False
    validate(workflow)
    return workflow


def validate(workflow: dict) -> None:
    raw = json.dumps(workflow).lower()
    for forbidden in ("10.0.70.202", ":8787", "podcast-worker", "ssh", "httprequest"):
        if forbidden in raw:
            raise ValueError(f"DeepSeek authoring workflow contains forbidden value: {forbidden}")
    models = [n for n in workflow["nodes"] if n["type"] == "@n8n/n8n-nodes-langchain.lmChatOllama"]
    if len(models) != 3 or any(n["parameters"].get("model") != MODEL for n in models):
        raise ValueError("all three DeepSeek attempts must use the pinned 0731 cloud tag")


if __name__ == "__main__":
    workflow = build()
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
