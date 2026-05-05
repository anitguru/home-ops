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
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Local model guardrail
When this profile uses `rgb-ollama / qwen3-coder:30b`, keep toolsets and MCPs narrow. Escalate to frontier models for high-risk code, public-facing content, unclear infra mutations, or repeated local-model confusion.
