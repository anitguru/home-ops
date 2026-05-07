# callnotes — Google Recorder → Obsidian meeting notes

Repo-backed Hermes/default-profile cron migration of the old Gitea `callnotes` workflow.

## Active runtime

- Default-profile Hermes cron runs `~/.hermes/scripts/callnotes_cron.sh`.
- That launcher is a thin `exec` into `/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/callnotes_cron.sh`.
- Durable logic lives in `/Users/sva/Documents/Repos/Github/home-ops/hermes/callnotes/callnotes.py`.
- Generative note structuring runs through `home-ops/hermes/scripts/hermes_llm.py` with `HERMES_AUTOMATION_PROFILE=callnotes`.

## Preserved behavior

- Scan Google Drive remote `svagml-remote-gdrive` for root-level `call.docx`.
- Convert DOCX transcript text with `python-docx`.
- Structure into Mortenson-style SentinelOne meeting notes.
- Write to Obsidian MCP vault `work` (`sva-s1`) folder `01_Interactions` as `<YYYY-MM-DD>-Call.md`.
- Force `[[Steve VanAllen]]` and preserve the old Steve alias normalization.
- Delete `call.docx` from Drive only after Obsidian write + read verification succeeds.
- No input exits cleanly with `NO_INPUT`.

## Secrets

`RCLONE_GDRIVE_CONF` is read at runtime from HashiCorp Vault by `vault_mcp_callnotes_env.py`. The wrapper never prints the value. The Python runtime writes the decoded rclone config only to a temporary `RCLONE_CONFIG` path and deletes it when the process exits.

## Safe checks

```bash
~/.hermes/scripts/callnotes_cron.sh --check
```

Check mode validates Vault secret presence, Python syntax/imports, temp rclone config access, and the `callnotes` one-shot Hermes profile without writing notes or deleting Drive input.
