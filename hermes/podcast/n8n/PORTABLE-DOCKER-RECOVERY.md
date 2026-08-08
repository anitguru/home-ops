# Portable podcast recovery and Docker migration

Updated: 2026-08-08 (America/New_York)

This is the recovery contract for the visible n8n implementation. A recovery
passes only when a fresh n8n instance plus an external Task Runner can import
the versioned JSON, attach credentials, and reproduce the manual staging run.
CT143 has no workflow API role and no podcast script is required there.
The former `podcast-worker.service` was read back disabled/inactive with port
8787 closed after the portable graph passed; do not restore or containerize it.

## Proven workflow graph

Import these exports in dependency order:

1. `bootstrap-podcast-run-ledger.json` — create the `podcast_run_ledger` Data
   Table if it was not restored with the n8n database.
2. `wf-podcast-sub-script-validator-v1.json` — publish this trigger-only child;
   it has no self-firing trigger and must be published for nested calls.
3. `wf-podcast-sub-intake-v1.json` — native Supabase and Hacker News intake.
4. `wf-podcast-sub-authoring-v1.json` — native GLM-5.2 with three bounded
   attempts and calls to the validator child.
5. `wf-podcast-sub-media-v1.json` — six serialized Chatterbox calls, native
   hash, visible assembly/QA routes, hard gate, and ledger.
6. `wf-podcast-sub-transcription-v1.json` — direct Whisper, compact authored
   word alignment, native Convert to File, native hash, hard gate, and ledger.
7. `wf-podcast-portable-staging-v1.json` — native Cloudinary upload, native
   GitHub file operations, rollback-only Postgres shape test, Telegram test
   notification, and ledger.
8. `wf-podcast-portable-shadow-v1.json` — thin 15-node parent calling the five
   children above.
9. `wf-error.json` — retain the existing error handler for eventual scheduled
   production use.

All podcast workflows import inactive. Do not publish the parent or add a
schedule during recovery. Only the script-validator child needs publication;
its live trigger count must remain zero.

The approved cleanup and Cloudinary verifier exports are historical recovery
evidence. They import MCP-disabled and must not be part of normal recovery:

- `wf-podcast-cleanup-approved-2026-08-08.json`
- `wf-podcast-cloudinary-cleanup-verify-2026-08-08.json`

## n8n image and Task Runner

- Pin n8n to the version validated by the exports (2.30.7) for the first
  recovery. Upgrade only after the staging acceptance test passes.
- Configure external Task Runners and restore the broker authentication token.
- The validated runner used launcher 1.4.7, Node 24.16.0, JavaScript runner
  2.30.3, Python 3.13.7, and the n8n 2.30.7 runner configuration.
- The runner needs no podcast repository, SSH key, ffmpeg, local artifact
  directory, worker token, or CT143 HTTP listener.
- Persist n8n's database and binary-data volume. Workflow JSON alone restores
  the design, but execution history, Data Tables, credentials, and retained
  binary evidence require the n8n data volumes or separate backups.

Install the verified Cloudinary community node in the n8n image before import:

```text
n8n-nodes-cloudinary@0.2.1
```

Record and review its npm audit during image builds. The validated install had
five upstream advisories (one moderate, four high, zero critical).

## Credentials to recreate

Create credentials by name/type; exported credential IDs are instance-local.
Use SOPS/age or the target platform's secret injection and never edit secrets
into workflow JSON.

| Name | n8n credential type | Used by |
| --- | --- | --- |
| `Supabase (podcast)` | `supabaseApi` | intake and eventual production rows |
| `Supabase Postgres (podcast)` | `postgres` | staging transaction/rollback proof |
| `Cloudinary (podcast)` | `cloudinaryApi` | native upload/asset operations |
| `GitHub Node (podcast)` | `githubApi` | native file create/get/delete |
| `GitHub API (podcast)` | `httpHeaderAuth` | branch/ref and absence operations missing from the native node |
| `Guru's Tech Bytes Bot (podcast)` | `telegramApi` | staging notification |
| existing Ollama Cloud credential | Ollama chat-model credential | GLM-5.2 authoring |

After import, reattach credentials by node type/name and export again to confirm
that no secret value entered the JSON.

## Voice and transcription services

The media workflow calls Chatterbox directly at
`https://chatterbox.transformers.lan/v1/audio`. The voice container must include
the versioned `../voice-service/portable_media.py` router and two-line server
hook documented in `../voice-service/README.md`. It exposes only:

- `GET /v1/audio/portable-health`
- `POST /v1/audio/assemble-six`
- `POST /v1/audio/objective-qa`

The container needs ffmpeg/ffprobe. These routes use per-request temporary
directories and retain no workflow state. TTS remains the existing
`POST /v1/audio/speech` service.

Whisper is called directly at
`https://whisper.transformers.lan/v1/audio/transcriptions` with
`response_format=verbose_json`, language `en`, and word timestamps.

The current exports set `allowUnauthorizedCerts=true` on the eight Chatterbox
HTTP nodes and the Whisper node because CT109 did not trust the Transformers
LAN issuer. In Docker, install the internal root/intermediate CA into the n8n
image and Node trust store, verify both HTTPS endpoints, remove those flags,
re-export, and rerun staging.

## Data Table

Restore or create `podcast_run_ledger` with the schema encoded in
`bootstrap-podcast-run-ledger.json`. The proven run wrote distinct rows for
start, intake, authoring, media QA, transcription QA, staging actions, and
cleanup evidence. Treat this table as operational history, not secret storage.

## Acceptance test after restore

1. Confirm no producer is scheduled and no TTS job is running.
2. Confirm n8n, the external runner, Chatterbox, and Whisper are healthy.
3. Verify every imported child and parent is inactive; verify the validator is
   published with no schedule/webhook trigger.
4. Run the parent manually outside 05:25–06:25 America/New_York.
5. Require terminal success for parent plus all five child executions.
6. Read back the final contract: one Cloudinary staging URL, one GitHub
   `podcast-shadow/` branch/file, database rollback true, Telegram message ID,
   audio/SRT hashes, objective audio QA, WER/anchor/layout QA, and ledger rows.
7. Download the Cloudinary staging MP3 and independently compare byte count and
   SHA-256 with the contract. Read the private GitHub branch/file back through
   authenticated GitHub access.
8. Confirm no production Cloudinary prefix, main-branch content file,
   `podcast_episodes` mutation, or production notification was created.

Reference acceptance evidence: parent execution 89, media 93, transcription
94, and staging distribution 95 succeeded on 2026-08-08. The MP3 was 1,117,101
bytes with SHA-256
`46e493b5766c7689ffb357be566ebb7ebee69ee1942f789bcdc7bb1d3fd314d2`;
the SRT SHA-256 was
`315fe6fac963117bd173298c842e5be1240c2fd78ae3f6248ddd33a856c38756`.

## Production cutover boundary

Both portable parents are proven: the staging parent and the separate
manual-production parent. The production parent is inactive, has only a Manual
Trigger, and calls the same reusable intake, authoring, media, and transcription
children before calling the production distribution child. The operator's
one-time authorization was used to prove those production destinations on
2026-08-08. It did not authorize a schedule or scheduler cutover.

A direct operator instruction to **cut over** is still required before:

- adding, publishing, or activating a schedule trigger; or
- changing Hermes/pi4/n8n scheduler ownership.

At cutover: back up n8n and all scheduler states, re-read Hermes/pi4/n8n live
ownership, activate exactly one producer, observe the first run through all
delivery readbacks, and roll back scheduler ownership on any hard failure.

## Approved duplicate cleanup recovery

Episode 125 dated 2026-08-08 was removed under explicit operator approval.
Recovery evidence is in Data Table rows 55 and 56 and Git commit
`64464c66fd57392b75d9488cbef82d44cda37f8d`. Cloudinary retained a deleted
placeholder for the old asset and a separate recovery copy at public ID
`anitguru-trash/gurus-tech-bytes-2026-08-08-episode-125-backup` (1,060,269
bytes). Restoring it is a separate production action and is not part of normal
Docker recovery.

## Clean manual-production acceptance evidence

The operator authorized deleting the first 2026-08-08 publication and running
the corrected primary production parent from an empty state. One-shot cleanup
execution 122 first copied the exact MP3 to
`anitguru-trash/gurus-tech-bytes-2026-08-08-episode-125-retest-backup`, then its
hard gate verified the production Supabase row absent, GitHub file absent after
commit `90d690577929ab2a44274136c4af99b0c2953fee`, and the Cloudinary production
asset absent.

Parent execution 123 then succeeded from 19:15:37–19:19:50 EDT. Its child
executions were intake 124, authoring 125 plus validator 126, media 127,
transcription 128, and production distribution 129. Acceptance values:

- MP3: 1,100,589 bytes, SHA-256
  `5926fc7378325fecc205071c289eb2de8f44dc6436730db1c9345878c9f6b73f`,
  137.544 seconds, -17.24 LUFS, -1.63 dBTP, zero clipped samples.
- SRT SHA-256:
  `3c5199e105162c593d9cd63b8e6e9ca54c598d02cdb651cc72410f6713421480`;
  WER 0.1477, exact-anchor ratio 0.898305, 38 cues, 47-character/two-line
  limits, and all beginning/middle/end anchors present.
- Cloudinary public ID `anitguru/gurus-tech-bytes-2026-08-08`; an independent
  download reproduced the byte count and MP3 hash.
- GitHub `main` commit `ca571e53e32f25250c68d9bd82a2c5e60516f81b`;
  `content/podcast/2026-08-08.md` blob
  `223b1433ffccaa4a53a338e3cee8f9a6f8192a61`.
- Native Supabase readback returned episode 125, four actual JSON story objects,
  the exact Cloudinary URL, and `duration_secs=138`.
- Native Telegram nodes returned message IDs 427, 428, and 429.
- Public `/podcast/ep-125` and `/podcast/feed.xml` both returned HTTP 200 and
  contained episode 125 plus the new audio URL.

The cleanup and partial-run recovery workflows were archived after this pass.
The production parent and production distribution child remain unarchived but
inactive/manual-only. Hermes remains paused; no n8n schedule exists.
