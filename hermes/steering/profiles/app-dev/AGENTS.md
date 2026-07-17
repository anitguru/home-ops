# AGENTS.md — app-dev Profile Workspace

This is the workspace steering for Hermes profile `app-dev`.

## Purpose
General app development learning, POCs/MVPs for individual projects, hobbies, and possible monetization paths.

## Default scope
Use only this profile's dependency tree unless the user explicitly asks to cross boundaries.

Repos:
- prompt-diet
- fun-learning-kids
- shrink
- logflow-lab
- snowball
- forest-adventure
- mr-fusion
- log-volume-calculator
- npm-structured-logger

Needs/tool domains:
- vault
- terminal
- file

MCP servers expected in this profile:
- vault
- cocoindex-home-ops

## Secrets
Use the canonical SOPS+age store and `secret` helper documented in the AnITGuru wiki for credentials. Do not print secret values.
Use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes` for SSH, Git signing/pushes, and unattended automation.

## Model routing
This profile should use `openai-codex / gpt-5.5` for agentic Hermes work. Keep toolsets/MCPs scoped to the task, and prefer deterministic no-agent scripts for low-risk recurring maintenance where practical.
