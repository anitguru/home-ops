# AGENTS.md — automations Profile Workspace

This is the workspace steering for Hermes profile `automations`.

## Purpose
Automations that support SVA hobby/brands/personas; migrate low-hanging Gitea Actions to Hermes cronjobs where practical.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- automations
- home-ops
- anit-guru

Needs/tool domains:
- vault
- cronjob
- terminal
- file
- firecrawl
- whisper
- tts

MCP servers expected in this profile:
- vault
- firecrawl
- cocoindex-automations
- cocoindex-home-ops
- cocoindex-anit-guru

## Secrets
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
