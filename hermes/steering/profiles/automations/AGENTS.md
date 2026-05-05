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
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Local model guardrail
When this profile uses `rgb-ollama / qwen3-coder:30b`, keep toolsets and MCPs narrow. Escalate to frontier models for high-risk code, public-facing content, unclear infra mutations, or repeated local-model confusion.
