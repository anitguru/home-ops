# AGENTS.md — xposting Profile Workspace

This workspace is for @anitdotguru X posting draft generation only.

- Default cwd/repo: `/Users/sva/Documents/Repos/Github/home-ops/hermes/x-social`
- Scheduling owner: default Hermes profile cronjobs
- Caller: home-ops repo-backed no-agent scripts such as `post_actions_cron.sh`
- No Gitea Actions, runners, or pushes are part of scheduled posting.

## Guardrails
- Produce one final answer only: the post body or requested structured response.
- Keep X posts within the caller's length budget; if unsure, make it shorter.
- Do not perform actual X API writes from this profile unless a prompt explicitly asks for the write and provides the exact intended target/action.
- Do not read or print credentials. Use HashiCorp Vault only when the task explicitly requires checking secret presence, and report only key names/presence.
