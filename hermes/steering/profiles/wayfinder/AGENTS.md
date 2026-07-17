# AGENTS.md — wayfinder Profile Workspace

This is the workspace steering for Hermes profile `wayfinder`.

## Purpose
Wayfinder/Athena creator community brand; high-traffic site, blog/content operations, newsletter/audience growth, humble monetization, and eventual Astro rebuild/import cleanup.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- wayfinder

Needs/tool domains:
- vault
- terminal
- file
- ahrefs
- firecrawl
- image_gen

MCP servers expected in this profile:
- vault
- ahrefs
- firecrawl

## Secrets
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
