# Guru's Tech Bytes — n8n Phase 1 handoff

Status as of 2026-08-04: **Phase 1 complete.** All three workflows are built,
validated in DRY_RUN/dry mode, and parked **disabled**. pi4's systemd timers
remain the sole live producer. **No cutover has happened.**

Plan: `docs/podcast-n8n-migration-phase1-plan.md` (claude-work repo) /
`personal/40-wiki/runbooks/podcast-n8n-migration-phase1.md` (vault).

## What exists in n8n (CT109, 10.0.0.188:5678)

| Workflow | ID | Active | Purpose |
|---|---|---|---|
| WF-podcast | `4PSoNGo9f91Wb34A` | **false** | Full decomposed podcast pipeline |
| WF-topic | `DGRWVbvFSQBtDAdU` | **false** | HN topic refresh (feeds cocoindex) |
| WF-error | `k5nmdOyJm5znKQzK` | **true** (see below) | Catches failures from other active workflows, alerts Telegram 🔴 |

Exported JSON for all three lives alongside this file (`wf-podcast.json`,
`wf-topic.json`, `wf-error.json`) — re-importable via n8n's UI or
`POST /api/v1/workflows`.

**Why WF-error is active while the others aren't:** n8n's error-workflow
mechanism requires the *target* workflow to be active to be invoked — but it
has no trigger of its own (just an Error Trigger node), so it can never fire
except in response to another *active* workflow's failure. Since WF-podcast
and WF-topic stay inactive all through Phase 1, WF-error sitting active is a
no-op until cutover. Verified via a disposable webhook-triggered failure test
(see execution log below) — confirmed n8n logs
`"Workflow ... is not active and cannot be executed"` when the target isn't
active, and confirmed the alert fires correctly once it is.

## Per-step I/O (the pi4 working-dir contract)

All steps share `/tmp/podcast-<date>/` on pi4 (same convention prod already
uses). Native n8n steps that produce a file a remote step needs write it there
over the SSH node before the next step reads it.

| # | Step | Placement | Reads | Writes |
|---|---|---|---|---|
| 1 | Episode # (COALESCE same-day / MAX+1) | native Postgres | — | (in-memory) |
| 2 | Fetch HN stories (Algolia) + normalize/dedupe | native HTTP + Code | — | (in-memory) |
| — | Write stories.json + metadata.json to pi4 | SSH | — | `stories.json`, `metadata.json` |
| 3 | cocoindex rank + proof-gate + recent-dedupe | SSH (`cocoindex_rank.py`) | `stories.json` | `ranked-stories.json`, `cocoindex-proof.json`, `rank.log` |
| — | Assert proof-gate (hard-fail on `Topic index unavailable` / missing proof) | native Code | rank stdout | throws on failure |
| 4 | Author script (GLM via Ollama, retry validators) | SSH (`pi4_generate_script.py`, fallback per plan) | `ranked-stories.json` | `script.txt`, `selected-stories.json` |
| 5 | TTS 6 segments + ffmpeg concat/loudnorm | SSH (`chatterbox_tts_segments.sh`) | `script.txt` | `episode.mp3` |
| — | Assert MP3 duration >60s | SSH (`ffprobe`) | `episode.mp3` | — |
| 6 | Whisper transcription | SSH (`curl`, **not** native HTTP — see below) | `episode.mp3` | `whisper-raw.json` |
| 7 | Build SRT from authored text | SSH (`pi4_build_srt.py`) | `script.txt` + `whisper-raw.json` | `episode.srt` |
| — | **`dryRun?` branch — Phase 1 always takes the true side** | native IF | `dryRun` flag | — |
| 8 | Publish (Cloudinary + site md + git push) | SSH (`publish-episode.mjs`, actual path `/home/pi/anit.guru/scripts/`, **not** home-ops as the original plan draft said) | `episode.mp3`, `selected-stories.json` | Cloudinary URL, git push |
| 9 | Upsert `podcast_episodes` | native Postgres | `audioUrl` | DB row |
| 10 | Deliver MP3 + SRT to Telegram | SSH (`curl`, **not** native Telegram node — see below) | `episode.mp3`, `episode.srt` | Telegram message |
| err | Any node failure → WF-error → Telegram 🔴 | workflow-level `settings.errorWorkflow` | — | Telegram alert |

## Deviations from the original plan table (and why)

The plan itself states large artifacts (audio) must never transit n8n. Two
placements in the original table would have violated that if taken literally:

- **Step 6 (Whisper)** — table said "native HTTP." A native HTTP Request node
  would need the MP3's bytes as binary input, which only exists on pi4. Built
  it as an SSH `curl` call instead (identical to what the prod script already
  does), so the audio only ever moves on-LAN between pi4 and whisper, never
  through n8n/CT109.
- **Step 10 (Telegram delivery)** — table said "native Telegram node." Same
  problem: the node's audio/document upload needs the file as binary data
  inside the execution. Built it as SSH `curl` calls mirroring the prod
  script's `tg_audio`/`tg_doc` functions.

Text-only Telegram (the DRY_RUN 🟡 summary, and WF-error's 🔴 alert) **is**
the native Telegram node — no artifact-transit concern there.

- **Step 4 (script authoring)** — table listed "native HTTP + JS (fallback:
  SSH)." Used the SSH fallback: `pi4_generate_script.py` already implements
  the retry/validator logic (6¶, 330–400w, ≤1 chuckle, GLM→Claude fallback)
  and was proven reliable in the Step B headless test before any n8n work
  started. Reimplementing that validation logic natively in n8n JS would risk
  behavior drift from what's actually running in prod, for no real benefit.
- **Step 8 (publish) path** — the plan draft referenced
  `publish-episode.mjs` living in home-ops; it actually lives at
  `/home/pi/anit.guru/scripts/publish-episode.mjs`. Corrected in the workflow.
- **WF-topic** — built via the plan's own sanctioned fallback (one SSH node
  calling `run-topic-refresh-pi4.sh`, no `--write`) rather than the fully
  native Algolia→Ollama→Supabase version, for the same reliability-over-
  reimplementation reasoning as step 4.

## Bugs found and fixed while building (useful if Phase 2 touches these nodes)

1. **`new URL(...)` is not available in n8n's Code-node sandbox** (task-runner
   process, restricted globals). The story-normalize step used it for domain
   dedup and silently produced 0 stories every run (every iteration threw,
   caught by a `try/catch`). Fixed with a regex-based domain extractor.
2. **n8n requires `=` as the first character of any parameter value that uses
   `{{ }}` expressions**, or the literal text (including the braces) is
   passed through unevaluated. Over SSH this is actively dangerous, not just
   inert — the literal `$('Node Name')` text collides with bash's own
   `$(...)` command-substitution syntax and gets shell-executed. All SSH
   `command` fields, Postgres query-replacement fields, and Telegram text
   fields must start with `=`.
3. **n8n's "error workflow" only fires for other *active* workflows**, and
   the error-workflow target itself must be active to be invoked at all — see
   the WF-error section above.
4. **Manually-triggered ("Run" button / `/rest/workflows/{id}/run`)
   executions never invoke the configured error workflow**, even if the
   workflow errors — only production-triggered executions (webhook, active
   schedule) do. Not a bug, just a testing gotcha: don't expect WF-error to
   fire from an interactive test run of WF-podcast.

## Validation performed (all in `dryRun`/dry mode, no prod writes)

- **Step A/B (pre-n8n-build):** new restricted SSH key
  (`from="10.0.0.188"`) added to pi4 `authorized_keys`; confirmed accepted
  only from CT109's IP. Headless `DRY_RUN=1 run-podcast-pi4.sh` run once via
  that key exactly as n8n would invoke it — clean secrets/venv load, full
  pipeline success (117.6s MP3, 24-cue SRT).
- **Step C:** all 5 n8n credentials (Ollama native, Ollama Bearer, Supabase
  REST, Supabase Postgres, Telegram, SSH) created and verified with real node
  executions (Ollama replied "pong", Supabase row query succeeded, Telegram
  message delivered, SSH `whoami` returned `pi` from the right host).
- **Step D/E (consolidated into one pass):** WF-podcast's full 17-node chain
  (1→7, proof-gate, dryRun branch) executed end-to-end successfully — 113.9s
  MP3, 24-cue SRT, correct 🟡 summary delivered to Telegram, steps 8–10 never
  touched (confirmed absent from the execution's node list). Ran once rather
  than once-per-node-then-again-full-chain, to avoid a redundant second TTS
  cycle against the shared Chatterbox box.
- **Step F:** WF-topic dry run succeeded (`dry run; 18 topic rows not
  written`, real Ollama extraction across 9 HN items). WF-error validated via
  a disposable webhook-triggered failure — confirmed it correctly identified
  the failing workflow/node/error message.
- Chatterbox contention checked before every TTS-touching test
  (`systemctl is-active chatterbox` + recent journal for in-flight
  generation). All testing done well outside the 05:25–06:25 ET prod window.
- pi4 timers (`gtb-topic-refresh.timer`, `gtb-podcast.timer`,
  `gtb-morning-check.timer`) confirmed enabled/active/untouched throughout —
  `systemctl --user list-timers` + `is-enabled`, checked as the final step.

## Open item for after today's 06:00 ET prod run

The plan calls for comparing the DRY_RUN's selected stories/episode# against
what pi4 actually publishes. That comparison couldn't happen yet — this work
was done ~00:20–00:52 ET, before today's real run. Worth a quick sanity check
after 06:00 ET: does prod's episode 121 story selection roughly match what
WF-podcast picked at 00:43 ET (same HN snapshot, same cocoindex ranking
logic)? Not blocking — just a nice-to-have cross-check.

## For Phase 2 / the eventual cutover

- Every remote-compute step above still binds to pi4 (Chatterbox TTS runs
  there via SSH, cocoindex/script-gen/SRT are pi4-local python+venv). Phase 2
  is about relocating that compute off pi4 onto a cleaner host — the
  SSH-node pattern here makes that a credential+host swap per node, not a
  rearchitecture.
- The real cutover is: disable pi4's three timers, enable WF-podcast's and
  WF-topic's Schedule Trigger nodes (already present in both, wired to 06:00
  and 05:30 America/New_York respectively, currently `disabled: true` at the
  node level), activate both workflows, flip `dryRun` to `false` in
  WF-podcast's Config node. Should be a deliberate, separately-approved step
  — not something to do casually off this handoff.
- `GENERIC_TIMEZONE` on the n8n service itself was **not** changed in Phase 1
  (out of scope — Schedule Trigger nodes carry their own
  `America/New_York` timezone regardless of instance-level config, so this
  wasn't blocking Phase 1 validation). Worth setting instance-wide before
  cutover for consistency in the UI/logs.
