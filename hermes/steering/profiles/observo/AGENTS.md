# AGENTS.md — observo Profile Workspace

This is the workspace steering for Hermes profile `observo`.

## Purpose
Event data logging pipeline for work-learning in homelab; sources from home infra; sinks include SigNoz primary, Splunk, and later SentinelOne Singularity Data Lake limited tests.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- observo
- home-ops

Needs/tool domains:
- vault
- terminal
- file

MCP servers expected in this profile:
- vault
- cocoindex-observo
- cocoindex-home-ops

## Secrets
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
