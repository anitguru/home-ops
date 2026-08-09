# Portable n8n podcast architecture

Updated: 2026-08-09 (America/New_York)

## Authoritative implemented graph

The portable implementation is a thin parent workflow calling five reusable
sub-workflows with native **Execute Sub-workflow** nodes:

1. `WF-podcast-sub-intake-v1`
2. `WF-podcast-sub-authoring-v1`
3. `WF-podcast-sub-media-v1`
4. `WF-podcast-sub-transcription-v1`
5. `WF-podcast-portable-staging-v1`

The parent is `WF-podcast-portable-shadow-v1`. This split is intentional: the
whole run is visible on the parent graph, each concern has its own inspectable
execution, and a child can be reused or fixture-tested without copying its
logic. The script validator is a still smaller reusable child called by the
authoring workflow. It is published only because n8n requires called workflows
to be available; it has no schedule or other self-firing trigger.

The production surface uses a separate thin parent,
`WF-podcast-portable-production-parent-v1`, which calls the same first four
children and then `WF-podcast-portable-production-v1`. The production child visibly performs the guarded Cloudinary,
GitHub, Supabase, and Telegram operations and their readbacks; it contains no
schedule, SSH node, CT143 URL, or hidden worker call. Clean-slate parent
execution 123 and production child execution 129 succeeded on 2026-08-08.

After explicit cutover authorization, the parent is active with one visible
native Schedule Trigger at 06:00 America/New_York plus its Manual Trigger. The
called children are published so n8n can invoke them, but none contains a
Schedule Trigger. `WF-error` is attached to scheduled production failures.

## CocoIndex ranking boundary

Production intake fetches 50 front-page items with the native Hacker News node,
normalizes them, and removes duplicate domains before visibly calling
`WF-podcast-sub-cocoindex-ranking-v1`. The dedicated child uses a native
Postgres node to read the persistent CocoIndex topic table and the last 45
episode story arrays. Small Python Code nodes on the versioned ARM64 runner
build stable story identities and score exact-boundary topic matches; separate
JavaScript nodes apply the recent-coverage penalty, sort, and emit a hard proof.
The child has no SSH node, CT143 API, file-based handoff, or Code-node network
call.

Execution 147 proved the child independently against 50 live topic rows and
537 recent story identity keys. Intake execution 148 then fetched 50 live HN
items, retained 45 domain-diverse candidates, called child execution 149, and
returned four non-duplicate stories with `cocoindex 0.3.9` / `aarch64` runtime
evidence. Exact topic boundaries still prevent errors such as matching `ai`
inside `Fastmail`.

## Authoring model A/B surface

The production parent now selects
`WF-podcast-sub-authoring-deepseek-v1`, which pins
`deepseek-v4-flash:0731-cloud` in the same three-attempt native Ollama/validator
shape. `WF-podcast-authoring-ab-v1` visibly calls both candidates with identical
stories and prompt, merges their contracts, records objective evidence in the
Data Table, and has no TTS or distribution nodes.

Frozen-fixture execution 131 passed: GLM validated on attempt 3 at 388 words;
DeepSeek validated on attempt 2 at 381 words; both returned six paragraphs.
GLM remains the quality/control candidate while DeepSeek is the lower-cost
production candidate.

The shared prompt now isolates the exact spoken greeting from all
meta-instructions, and the reusable validator hard-fails known prompt,
formatting, or corrective-feedback fragments in narration. Negative regression
execution 152 rejected the injected sentence `Never put digits in the greeting`
with explicit leakage proof. Fresh A/B execution 154 then passed: GLM on
attempt 1 at 387 words and DeepSeek on attempt 2 at 390 words, both with six
paragraphs, empty validation errors, and `promptLeakageDetected=false`.

The 2026-08-09 scheduled execution 160 exposed n8n's draft/published boundary:
manual A/B execution 154 had exercised the corrected drafts, while scheduled
authoring execution 162 and validator execution 163 used older active versions
and allowed the prior prompt sentence through. The four changed workflows were
then explicitly published and read back with `versionId == activeVersionId`.
Published-version regression execution 167 called A/B, GLM, DeepSeek, and
validator executions 168–173; every execution version matched its active
version. GLM passed at 380 words and DeepSeek at 397 words, both with empty
validation errors and no leakage. Future workflow updates require this active
version equality plus an integrated published-version test.

Production retest execution 218 exposed a DeepSeek corrective-loop weakness:
the retry prompt embedded the entire oversized prior draft, so two later runs
reproduced or truncated it. The published DeepSeek child now gives explicit
per-paragraph word budgets and builds retries from the original prompt plus
validation errors only. Published authoring execution 221 then passed on its
first attempt at 387 words, six paragraphs, and no leakage. Media execution 223
and transcription execution 224 passed at 130.344 seconds, -17.11 LUFS,
-1.68 dBTP, zero clipping, WER 0.134146, and 0.9 exact-anchor ratio.

Distribution execution 225 created the Cloudinary asset and GitHub commit but
hit GitHub's brief post-commit 404 on immediate native readback. n8n's visible
saved-input retry execution 227 resumed at the failed node and completed
GitHub verification, Supabase persistence, three Telegram deliveries, and the
final ledger. The production GitHub readback node is now published with a
bounded four-attempt, two-second retry to absorb this consistency window.

Episode-repair execution 228 later demonstrated a second consistency behavior:
GitHub may return HTTP 200 with the old file contents immediately after a
successful native Edit File operation. Because a successful stale response does
not activate `retryOnFail`, the repair graphs now place a visible five-second
Wait node before the native GitHub readback and then hard-check the expected
content SHA, transcript, and Cloudinary URL.

## Historical audio and timestamp repair surface

The episode 123/124 repair workflows are purpose-built one-shots, not hidden
host scripts. They recover the committed transcript through the native GitHub
node, enforce the exact target episode/date and spoken-number greeting, call the
published reusable media and transcription children, validate objective audio
and alignment evidence, upload through the Cloudinary node, edit/read back the
site through GitHub nodes, update/read back Supabase through native nodes, and
write the final Data Table ledger. They contain no SSH or schedule nodes. After
successful production execution and independent readback, the live one-shots
are archived while their builders and JSON exports remain versioned here.

## Model evaluation economics

`MODEL-EVALUATION-PLAN.md` defines the graph-visible A/B/N evidence contract.
The key decision metric is total cost per human-accepted episode, including all
failed/retried attempts. It pairs per-attempt latency, token/cost, validator and
leakage evidence with a blinded listening review. GLM is the quality control;
DeepSeek is the current production candidate; Qwen joins only after its exact
available model tag is verified. Scheduled candidates must use durable API-key
or local credentials rather than interactive subscription sessions.

The same audit found that scheduled intake execution 161 had used its older
published lexical scorer: the CocoIndex child existed only as an unpublished
draft dependency. The CocoIndex child and intake were published in dependency
order. Published webhook regression execution 177 then called intake 178 and
CocoIndex 179 on their exact active version IDs. It passed with 46 candidates,
four unique non-duplicates, 50 indexed topics, CocoIndex 0.3.9, and ARM64
runtime proof. The temporary caller was archived afterward.

CT143 is **only** the external n8n Task Runner. The implemented portable graph
contains no SSH nodes, CT143 URL, or `podcast-worker` dependency. Voice and
Whisper are direct service calls from visible nodes. Cloudinary, GitHub,
Supabase/Postgres, Telegram, Crypto, Data Table, file conversion, loops, IF
branches, and sub-workflow calls use native nodes where the needed operation is
available. HTTP Request nodes are limited to APIs or API operations that the
installed native node does not expose, and their node notes record the reason.

The older CT143 worker-based designs and disconnected islands remain historical
test evidence only. They are not the recovery architecture and must not be
restored as runtime dependencies.

The verified recovery/import procedure is in
`PORTABLE-DOCKER-RECOVERY.md`.

## Recovery test

The production design passes only when a fresh n8n control plane plus its
external task runner can recover from the exported workflow JSON, declared
runner image dependencies, and restored n8n credentials/environment secrets.
No podcast business logic may live only in an LXC filesystem, helper daemon,
pre-cloned repository, or SSH target.

## Runtime boundaries

- n8n owns orchestration, branching, retry, iteration, validation, and state.
- CT143 is temporarily an external n8n JavaScript-only Task Runner. pi1 is the
  versioned ARM64 JavaScript/Python runner and the sole Python task provider.
  Workflows contain no CT143/pi1 HTTP URL and no SSH node.
- Stable service APIs are called directly from visible nodes: CT137/RGB voice,
  Ollama, CT131 Whisper, Cloudinary, GitHub, Postgres, and Telegram.
- Prefer the built-in service node whenever it supports the required action.
  A generic HTTP Request node is allowed only when no built-in integration is
  installed or the built-in node lacks that specific API operation; its note
  must name the missing capability.
- Small Code nodes may transform or validate one concern. Podcast business
  logic must be embedded in the exported workflow, not imported from a local
  script. Code-node blocks are limited to 100 nonblank lines.
- Binary audio moves as n8n binary items. Temporary files used by a declared
  media runtime are execution-scoped and disposable; they are not handoff
  state.
- The external runner image may contain declared generic runtimes such as
  ffmpeg. It may not contain podcast-specific scripts.

## Visible node decomposition

| Concern | Visible n8n shape |
| --- | --- |
| Episode/date safety | Config -> mode guard -> Postgres episode lookup |
| Story ranking | Native HN top 50 -> normalize -> domain dedupe -> Execute CocoIndex child -> native Postgres index/recent reads -> modular ARM64 scoring/penalty/proof -> select four |
| Authoring | Prepare prompt -> native Ollama model -> reusable validator -> IF retry, capped at three; separate GLM/DeepSeek A/B harness |
| Voice | Split six paragraphs -> Loop Over Items -> CT137 HTTP -> IF failure -> RGB HTTP -> segment hash/probe -> aggregate |
| Audio | Direct voice-service render -> direct voice-service assembly/normalization -> objective QA -> hard IF gate |
| Subtitles | CT131 Whisper HTTP -> normalize timeline -> edit alignment -> interpolate authored words -> format SRT -> alignment QA |
| Cloudinary | Native Cloudinary upload -> HTTP HEAD verification because the community node lacks a delivery verification operation |
| Site/feed | Generate markdown -> GitHub branch/ref API -> GitHub content commit API -> commit/check verification |
| Database | Native Supabase/Postgres staging operation with explicit rollback in staging |
| Notification | Telegram text/audio/SRT nodes after database verification |
| Manifest | Build hashes/provenance -> upload durable manifest -> verify hash |

## Builder invariants

The versioned builder must fail if a generated workflow contains:

- an SSH node;
- a CT143 address, port 8787, or `podcast-worker` reference;
- `executeCommand` or a call to an undeclared arbitrary endpoint;
- a Code node over 100 nonblank lines;
- a production distribution edge that bypasses its explicit mode and quality
  gates;
- schedule activation in a shadow workflow.
