# AGENTS.md — tvauto Profile Workspace

This is the workspace steering for Hermes profile `tvauto`.

## Purpose
Automate TV show downloads and management; version control homelab app/config data and related public link site/deployable files.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- tvauto
- tvauto.io

Needs/tool domains:
- vault
- terminal
- file

MCP servers expected in this profile:
- vault
- cocoindex-home-ops

## Secrets
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Local model guardrail
When this profile uses `rgb-ollama / qwen3-coder:30b`, keep toolsets and MCPs narrow. Escalate to frontier models for high-risk code, public-facing content, unclear infra mutations, or repeated local-model confusion.
