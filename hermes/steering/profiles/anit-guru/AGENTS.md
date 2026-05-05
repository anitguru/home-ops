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
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Local model guardrail
When this profile uses `rgb-ollama / qwen3-coder:30b`, keep toolsets and MCPs narrow. Escalate to frontier models for high-risk code, public-facing content, unclear infra mutations, or repeated local-model confusion.
