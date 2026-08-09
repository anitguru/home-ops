#!/usr/bin/env python3
"""Build the portable n8n Data Table bootstrap workflow.

The table stores small, inspectable run checkpoints. Audio and subtitle binary
artifacts deliberately do not belong in the ledger.
"""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "bootstrap-podcast-run-ledger.json"

WORKFLOW_ID = "pRunLedgerX8Q3M7Z"
TABLE_NAME = "podcast_run_ledger"

COLUMNS = [
    ("run_id", "string"),
    ("execution_id", "string"),
    ("run_mode", "string"),
    ("episode", "number"),
    ("episode_date", "string"),
    ("stage", "string"),
    ("status", "string"),
    ("attempt", "number"),
    ("selected_stories_json", "string"),
    ("script_sha256", "string"),
    ("audio_sha256", "string"),
    ("srt_sha256", "string"),
    ("tts_processor", "string"),
    ("tts_endpoint_host", "string"),
    ("tts_profile", "string"),
    ("qa_json", "string"),
    ("artifact_urls_json", "string"),
    ("error", "string"),
    ("started_at", "date"),
    ("updated_at", "date"),
]


def build() -> dict:
    workflow = {
        "id": WORKFLOW_ID,
        "name": "bootstrap-podcast-run-ledger",
        "active": False,
        "nodes": [
            {
                "id": "manual_trigger",
                "name": "Manual Ledger Bootstrap",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "create_ledger",
                "name": "Ensure Podcast Run Ledger",
                "type": "n8n-nodes-base.dataTable",
                "typeVersion": 1.1,
                "position": [240, 0],
                "parameters": {
                    "resource": "table",
                    "operation": "create",
                    "tableName": TABLE_NAME,
                    "columns": {
                        "column": [
                            {"name": name, "type": column_type}
                            for name, column_type in COLUMNS
                        ]
                    },
                    "options": {"createIfNotExists": True},
                },
                "notes": "Idempotently creates the portable metadata ledger; binary artifacts never enter this table.",
            },
            {
                "id": "ledger_stop",
                "name": "Ledger Ready",
                "type": "n8n-nodes-base.noOp",
                "typeVersion": 1,
                "position": [480, 0],
                "parameters": {},
            },
        ],
        "connections": {
            "Manual Ledger Bootstrap": {
                "main": [[{"node": "Ensure Podcast Run Ledger", "type": "main", "index": 0}]]
            },
            "Ensure Podcast Run Ledger": {
                "main": [[{"node": "Ledger Ready", "type": "main", "index": 0}]]
            },
        },
        "settings": {"executionOrder": "v1"},
        "meta": {"templateCredsSetupCompleted": True},
        "pinData": {},
        "tags": [],
    }
    assert len({name for name, _ in COLUMNS}) == len(COLUMNS)
    assert all(column_type in {"boolean", "date", "number", "string"} for _, column_type in COLUMNS)
    return workflow


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
