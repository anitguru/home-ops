# Podcast authoring model evaluation

Updated: 2026-08-09 (America/New_York)

## Decision rule

Choose an unattended API-key or local model by **total cost per accepted
episode**, not quoted token price. GLM remains the quality control. DeepSeek is
the current production candidate, and Qwen can join the comparison after its
exact available model tag is verified. Subscription-session authentication is
not eligible for scheduled production because an interactive refresh can stop
the pipeline.

## Visible n8n shape

Extend the distribution-free authoring A/B workflow into an A/B/N evaluator.
It fans the same immutable story set, prompt version, date, weekday, and episode
number to each model child. Every child keeps its existing validator and bounded
three-attempt retry. A merge/normalization branch writes one Data Table row per
attempt and one summary row per candidate; no TTS or distribution node belongs
in this evaluator.

Use two Data Tables:

- `podcast_model_attempts`: `evaluation_id`, `run_id`, `episode`, `date`,
  `candidate`, `model`, `endpoint_class`, `prompt_version`, `attempt`,
  `latency_ms`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`,
  `validated`, `validation_errors_json`, `prompt_leakage_detected`, `word_count`,
  `paragraph_count`, and `script_sha256`.
- `podcast_model_reviews`: `evaluation_id`, randomized `sample_label`,
  `opening_score`, `humor_score`, `naturalness_score`, `accuracy_score`,
  `listening_preference`, `accepted`, `reviewed_at`, and optional notes. The
  label-to-model mapping stays hidden until the review is recorded.

The evaluator must retain failed attempts. For a candidate and review window:

`cost_per_accepted_episode = sum(cost of every attempt) / accepted episodes`

For local models, replace token charges with an explicit operating estimate
(`runtime_hours * measured host watts / 1000 * electricity_rate`, plus any
chosen hardware-amortization rate) so local and API candidates are comparable.

## Automated gates and dashboard metrics

Keep the current hard requirements: exact greeting and closing, six paragraphs,
330-400 words, all four stories represented, no prompt/corrective-feedback
leakage, and success within three attempts. Aggregate first-attempt pass rate,
eventual pass rate, attempts per accepted script, leakage count, median/p95
latency, tokens, raw spend, and cost per accepted episode. Data Table views are
the source of truth; a separate read-only reporting workflow may post a weekly
Telegram summary.

## Promotion gate

Evaluate at least 20 comparable live or frozen-fixture runs before promotion.
A candidate must have:

- at least 95% eventual validation success within three attempts;
- at least 80% first-attempt success;
- zero prompt leakage;
- no material story-accuracy regression;
- blind listening results non-inferior to GLM for humor and naturalness; and
- a meaningfully lower cost per accepted episode (target: at least 50% lower).

Keep GLM as a visible fallback until the promoted candidate completes a further
production observation window without a hard authoring failure. A model/tag,
prompt, validator, or pricing change starts a new evaluation cohort rather than
silently mixing unlike results.
