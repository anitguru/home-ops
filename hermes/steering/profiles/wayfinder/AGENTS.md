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
Use HashiCorp Vault for shared/durable credentials. Do not print secret values. Avoid 1Password access; move specific agent-needed secrets to HashiCorp Vault intentionally.

## Local model guardrail
When this profile uses `rgb-ollama / qwen3-coder:30b`, keep toolsets and MCPs narrow. Escalate to frontier models for high-risk code, public-facing content, unclear infra mutations, or repeated local-model confusion.
