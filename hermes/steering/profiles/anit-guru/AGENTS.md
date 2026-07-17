# AGENTS.md — anit-guru Profile Workspace

This is the workspace steering for Hermes profile `anit-guru`.

## Purpose
Main SVA/AnITGuru persona site, X social, YouTube, Guru's Tech Bytes, audience-building and monetization goals.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- anit-guru
- home-ops

Needs/tool domains:
- vault
- web
- terminal
- file
- ahrefs

MCP servers expected in this profile:
- vault
- ahrefs
- cocoindex-anit-guru
- cocoindex-home-ops

## Secrets
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
