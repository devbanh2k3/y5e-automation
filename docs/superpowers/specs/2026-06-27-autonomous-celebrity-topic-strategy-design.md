# Autonomous Celebrity Topic Strategy Design

## Goal

Make Celebrity batch production choose diverse, production-ready topics autonomously. A batch must not converge on minor title variations of the same ranking, and repeated runs must retain durable topic memory.

## Scope

This change adds topic strategy before `ContentAgent`. It changes topic selection and batch orchestration only. It does not change video templates, image ranking, review behavior, analytics, or upload.

## Architecture

Add a `TopicStrategyAgent` with four responsibilities:

1. Load durable Celebrity topic history.
2. Ask AI for a candidate pool larger than the requested batch.
3. normalize, validate, deduplicate, and score candidates.
4. Reserve the best diverse candidates before content generation starts.

`ContentAgent` will accept an explicit selected topic. It will no longer choose a new topic when the batch has already selected one. Single-video production will use the same strategy with a requested count of one.

## Open Taxonomy

The strategy starts with seed dimensions such as wealth, earnings, social reach, awards, film, music, age, physical measurements, career duration, country, generation, and profession. These are discovery hints, not a fixed allowlist.

AI may propose new categories, angles, and metrics. A new dimension is accepted only when it is measurable, suitable for public-source verification, likely to have real-person imagery, and safe for publication. Gossip, private allegations, medical claims, and other sensitive speculation are rejected.

## Candidate Contract

Each candidate contains:

- `title`
- `category`
- `angle`
- `metric_label`
- `entity_type`, restricted to individual people for the current template
- `data_availability_reason`
- `image_availability_reason`
- `viral_reason`
- `time_scope` when the metric is time-sensitive

The agent requests at least five candidates per desired video, with a reasonable upper bound to control AI cost.

## Selection And Scoring

Candidates are scored on a 100-point scale:

- Viral potential: 30
- Public data availability: 25
- Novelty against history and the current batch: 25
- Real image availability: 15
- Publication safety: 5

Deterministic validation runs before scoring. Invalid candidates cannot be rescued by a high AI score. The selector then chooses the highest-scoring set subject to diversity constraints rather than simply taking the highest individual scores.

Within one batch:

- No duplicate normalized topic.
- No repeated `angle` or `metric_label` unless no valid alternative exists; production fails clearly instead of silently producing near-duplicates.
- Semantic similarity between candidate titles and selected topics must stay below the configured duplicate threshold.

Across runs:

- The same angle has a cooldown covering the 10 most recently reserved videos.
- A semantically equivalent topic remains excluded across full history unless its `time_scope` or underlying data has materially changed.
- Reusing some individual celebrities is allowed because the compared metric and editorial question may differ.

## Durable History And Reservation

Store topic records in a dedicated JSON repository under the configured storage directory for the MVP. Writes use an atomic replace to avoid partial files. The repository holds an inter-process file lock across the read-reserve-write transaction so concurrent batches cannot reserve equivalent topics.

Each record contains candidate fields, score breakdown, status, timestamps, batch ID, topic ID when available, and failure reason. Supported states are `reserved`, `produced`, and `failed`.

A topic is reserved before content generation. This prevents later items in the same batch or a subsequent process from selecting it again. Successful production marks it `produced`. Failed production marks it `failed`; the strategy may select the next valid candidate, but the failed topic remains in history for diagnosis.

## Batch Flow

1. Batch requests `count` topics from `TopicStrategyAgent`.
2. Strategy generates, validates, scores, and reserves a diverse slate.
3. Each reserved topic is passed explicitly into single-video production.
4. `ContentAgent` builds scenes for that exact topic.
5. Existing image verification, render, quality gate, and review flow remains unchanged.
6. A failed item receives one replacement topic when the candidate pool permits it.
7. The final summary includes selected topic, category, angle, metric, total score, score breakdown, and selection reason.

## Failure Handling

- Invalid AI JSON is retried through the existing AI client behavior.
- Too few diverse candidates triggers one expanded candidate-generation pass.
- If diversity still cannot be satisfied, the batch reports a topic-selection failure instead of rendering duplicate videos.
- History read corruption produces a clear error and preserves the corrupt file for inspection.
- History write failure stops reservation; production must not proceed without durable deduplication state.

## Testing

Focused tests will prove:

- Near-identical title variants are detected as duplicates.
- The 10-video angle cooldown is enforced.
- New AI-proposed taxonomy dimensions are accepted only after validation.
- A requested batch receives distinct angles and metrics.
- Reservations persist across separate strategy instances.
- Concurrent reservation attempts cannot select the same topic.
- Failed production is recorded and replacement selection works.
- The selected topic is passed unchanged from batch orchestration to `ContentAgent`.
- Batch JSON exposes topic and score information.

The full existing test suite must continue to pass.

## Non-Goals

- Channel analytics feedback
- YouTube upload or scheduling
- Automatic performance-based weight tuning
- A graphical topic approval interface
- Further image or template optimization
