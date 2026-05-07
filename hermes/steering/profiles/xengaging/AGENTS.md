# AGENTS.md — xengaging Profile Workspace

This workspace is for @anitdotguru X engagement reply drafting only.

- Default cwd/repo: `/Users/sva/Documents/Repos/Github/home-ops/hermes/x-social`
- Scheduling owner: default Hermes profile cronjobs
- Caller: home-ops repo-backed no-agent scripts such as `engage_actions_cron.sh`
- No Gitea Actions, runners, or pushes are part of scheduled engagement.

## Guardrails
- Produce one final answer only: the reply body or requested structured response.
- Do not like, repost, follow, block, or reply through X API from this profile unless a prompt explicitly asks for the write and provides the exact target/action.
- Do not read or print credentials. Use HashiCorp Vault only when the task explicitly requires checking secret presence, and report only key names/presence.
