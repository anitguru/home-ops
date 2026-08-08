#!/usr/bin/env python3
"""Build an inert one-shot origin verifier for the approved Cloudinary deletion."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "wf-podcast-cloudinary-cleanup-verify-2026-08-08.json"
CREDENTIAL = {"cloudinaryApi": {"id": "pCloudinaryX8Q3M7", "name": "Cloudinary (podcast)"}}


def build() -> dict:
    nodes = [
        {"id": "manual", "name": "Manual Cloudinary Cleanup Verify", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0], "parameters": {}},
        {"id": "context", "name": "Exact Deleted Asset Context", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [240, 0], "parameters": {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": "return [{json:{assetId:'ae11b2444759a36eefca31e9c8b094d8',publicId:'anitguru/gurus-tech-bytes-2026-08-08'}}];"}},
        {"id": "get", "name": "Cloudinary - Get Deleted Asset by Immutable ID", "type": "n8n-nodes-cloudinary.cloudinary", "typeVersion": 2, "position": [480, 0], "parameters": {"resource": "asset", "operation": "getAsset", "assetId": "={{ $json.assetId }}"}, "credentials": CREDENTIAL, "onError": "continueRegularOutput"},
        {"id": "gate", "name": "Hard Cloudinary Origin Absence Gate", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [720, 0], "parameters": {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": "const r=$input.first().json;const deletedPlaceholder=r.placeholder===true&&Number(r.bytes)===0&&r.backup===true;if(!deletedPlaceholder&&!r.error) throw new Error('Cloudinary origin asset still exists');return [{json:{cloudinaryOriginAbsent:true,deletedPlaceholder,detail:r.error?String(r.error):'placeholder=true,bytes=0,backup=true'}}];"}},
        {"id": "stop", "name": "Cloudinary Cleanup Verification Stop", "type": "n8n-nodes-base.noOp", "typeVersion": 1, "position": [960, 0], "parameters": {}},
    ]
    connections = {a["name"]: {"main": [[{"node": b["name"], "type": "main", "index": 0}]]} for a, b in zip(nodes, nodes[1:])}
    return {"id": "pCloudVer125X8Q3", "name": "WF-podcast-cloudinary-cleanup-verify-2026-08-08", "active": False, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "availableInMCP": False}, "meta": {"templateCredsSetupCompleted": True}, "pinData": {}, "tags": []}


if __name__ == "__main__":
    workflow = build()
    raw = json.dumps(workflow).lower()
    assert not any(x in raw for x in ("ssh", "podcast-worker", "scheduletrigger", "executeworkflowtrigger"))
    OUTPUT.write_text(json.dumps(workflow, indent=2) + "\n")
    print(OUTPUT)
