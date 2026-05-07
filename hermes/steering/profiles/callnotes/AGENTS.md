# AGENTS.md — callnotes Profile Workspace

This workspace is for call transcript note structuring only.

- Default cwd/repo: `/Users/sva/Documents/Repos/Github/home-ops/hermes/callnotes`
- Scheduling owner: default Hermes profile cronjob
- Caller: repo-backed script `/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/callnotes_cron.sh`
- Runtime side effects (Drive scan/download/delete and Obsidian writes) are owned by the wrapper/Python script, not by this profile.

## Guardrails

- Produce one final answer only: raw markdown note content, or the exact requested smoke-test phrase.
- Do not read or print credentials.
- Do not call direct provider CLIs/SDKs or Anthropic/Claude APIs.
- Do not use Gitea Actions, runners, or `git push` as part of scheduled callnotes runtime.
- Do not launch interactive editors during automated one-shot runs.
