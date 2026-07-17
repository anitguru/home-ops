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
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
