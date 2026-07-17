# AGENTS.md — game-server-ops Profile Workspace

This is the workspace steering for Hermes profile `game-server-ops`.

## Purpose
Infra ops for Enemy Territory/ETLegacy public servers, ET Trick Jump private, Unreal Tournament 99, downloads.vanhero.com Caddy/files, and VanHero stats pipeline.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- game-servers
- home-ops
- vanhero

Needs/tool domains:
- vault
- cronjob
- terminal
- file

MCP servers expected in this profile:
- vault
- cocoindex-home-ops
- cocoindex-vanhero

## Secrets
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
