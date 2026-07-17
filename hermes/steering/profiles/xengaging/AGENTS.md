# AGENTS.md — xengaging Profile Workspace

This workspace is for @anitdotguru X engagement reply drafting only.

- Default cwd/repo: `/Users/sva/Documents/Repos/Github/home-ops/hermes/x-social`
- Scheduling owner: default Hermes profile cronjobs
- Caller: home-ops repo-backed no-agent scripts such as `engage_actions_cron.sh`
- No Gitea Actions, runners, or pushes are part of scheduled engagement.

## Guardrails
- Produce one final answer only: the reply body or requested structured response.
- Do not like, repost, follow, block, or reply through X API from this profile unless a prompt explicitly asks for the write and provides the exact target/action.
- Do not print credentials. Retrieve required values through the canonical SOPS+age `secret` helper workflow and report only key names/presence.
- Any SSH or Git operation must use `~/.ssh/id_ed25519_orionpax` with `IdentityAgent=none` and `IdentitiesOnly=yes`; do not depend on the 1Password SSH agent.
