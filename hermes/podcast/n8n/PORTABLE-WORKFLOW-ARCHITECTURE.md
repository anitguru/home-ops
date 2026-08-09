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

## Ranking fidelity boundary

The portable production graph does not run CocoIndex. Historical fixture fields
named `cocoindexReason` are provenance residue, not evidence of a live semantic
ranker. Production intake currently uses the visible
`visible-token-topic-score-v2` pipeline: native Hacker News fetch of 50 front
page items, URL/title normalization, domain deduplication, exact token/phrase
technology aliases, HN-score weighting, deterministic sort, and selection of
four domains. Exact boundaries prevent errors such as matching `ai` inside
`Fastmail`.

This is transparent and portable, but it is still lexically shallower than
CocoIndex/embedding similarity and does not yet restore semantic novelty or
recent-coverage ranking. Do not describe token scoring as equivalent fidelity.
Execution 139 proved 50 fetched items, 46 domain-diverse candidates, and zero
false `ai` matches.

## Authoring model A/B surface

GLM-5.2 remains the production authoring child. The optional
`WF-podcast-sub-authoring-deepseek-v1` pins
`deepseek-v4-flash:0731-cloud` in the same three-attempt native Ollama/validator
shape. `WF-podcast-authoring-ab-v1` visibly calls both candidates with identical
stories and prompt, merges their contracts, records objective evidence in the
Data Table, and has no TTS or distribution nodes.

Frozen-fixture execution 131 passed: GLM validated on attempt 3 at 388 words;
DeepSeek validated on attempt 2 at 381 words; both returned six paragraphs.
Human style preference remains pending, so production still selects GLM.

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
- CT143 is only an external n8n JavaScript/Python Task Runner. Workflows must
  contain no CT143 HTTP URL and no SSH node.
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
| Story ranking | Native HN top 50 -> normalize -> domain dedupe -> exact token/phrase score -> deterministic sort -> select four -> proof gate |
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
