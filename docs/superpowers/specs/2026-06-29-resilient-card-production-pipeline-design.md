# Resilient Card Production Pipeline Design

## Objective

Make long-form celebrity video production reliable without regenerating an entire video when a small number of cards fail. The pipeline must prepare a globally unique subject list before scene generation, preserve every valid result, repair or replace failed cards independently, and render when a configurable minimum number of quality cards is available.

This design changes content orchestration and failure handling only. It does not change video templates, analytics, review, publishing, or the current real-image quality strategy.

## Design Principles

1. Plan subjects once, then write scenes only for locked subjects.
2. Validate deterministic rules in code instead of relying on prompt instructions.
3. Preserve valid partial output from every AI response.
4. Handle failures at the smallest possible scope: field, card, chunk, then run.
5. Repair first, replace second, skip last.
6. Fail a run only for a system-level error or insufficient quality inventory.
7. Persist checkpoints so a worker restart does not repeat completed work.

## Pipeline

```text
Topic selection
  -> Entity planner
  -> Global candidate gate
  -> Locked primary and reserve candidates
  -> Chunked scene writer
  -> Card-level content repair
  -> Fact verification and repair
  -> Real-image verification and replacement
  -> Minimum-card gate
  -> Reindex and reconcile metadata
  -> Render
  -> Existing review and publishing flow
```

## Entity Planning

The entity planner generates compact candidate records instead of complete scenes. For a requested `target_cards`, it should request an oversampled candidate pool:

```text
reserve_cards = max(10, ceil(target_cards * 0.25))
requested_candidates = target_cards + reserve_cards
```

Each candidate contains only the fields needed for selection:

```json
{
  "name": "Ariana Grande",
  "countryCode": "US",
  "selectionReason": "Strong fit for the requested metric",
  "aliases": []
}
```

The planner may return fewer candidates than requested. Valid candidates are retained and only the deficit is requested again. Subsequent requests include a blacklist of already accepted and rejected normalized names.

## Global Candidate Gate

Candidate validation runs before scene writing and is deterministic where possible.

The gate:

- normalizes names, punctuation, spacing, and known aliases;
- rejects duplicate people within the run;
- rejects unsupported group entities when the card contract requires one person;
- validates `countryCode` against the supported country registry;
- checks recent production history to reduce repeated subjects;
- performs a lightweight real-image availability precheck;
- records rejection reasons for diagnostics;
- ranks candidates by topic fit, fact verifiability, image availability, and novelty.

The selected primary list is immutable for normal scene generation. Remaining accepted candidates become the ordered reserve pool. A replacement operation consumes one reserve candidate atomically so two failed cards cannot receive the same person.

## Scene Writing

The scene writer continues to use bounded chunks to avoid oversized or truncated AI responses. Chunking is an implementation detail, not a content-selection step.

Each request receives an exact locked subject list and must return one scene per subject. The writer is not allowed to introduce new subjects. The response is reconciled by normalized subject identity rather than array position.

For every response:

- valid matching scenes are accepted immediately;
- missing subjects remain pending;
- unknown or duplicate subjects are discarded;
- invalid scenes are sent to card-level repair;
- only pending subjects are requested again.

The final scene order follows the locked primary list, independent of AI response order.

## Safe AI Call Boundary

All planner, writer, repair, and verification requests use one shared safe-call boundary. Callers receive structured success or failure results rather than raw parser exceptions.

### Transport failures

Timeouts, connection errors, HTTP 429, and retryable 5xx responses use exponential backoff with jitter. The default maximum is three transport attempts. Non-retryable authentication and configuration errors stop the run as system failures.

### Malformed JSON

The parser attempts, in order:

1. parse the response directly;
2. extract JSON from a Markdown fence or surrounding prose;
3. repair common structural damage locally when unambiguous;
4. ask the AI to return a corrected JSON representation;
5. retry with a shorter request containing only missing items.

JSON repair is limited to two AI repair attempts. Valid items recovered from a partially valid collection are retained before retrying missing items. Raw invalid responses and parser errors are stored in diagnostics with secrets removed.

### Contract failures

Schema validation returns field-level errors. A scene with one invalid field is repaired as one card; it does not invalidate sibling scenes or its entire chunk.

## Card State Machine

Each planned card has durable state:

```text
planned
  -> content_generating
  -> content_ready
  -> fact_checking
  -> fact_ready
  -> image_searching
  -> ready

Any non-terminal state may transition to:
  -> repairing
  -> replacing
  -> skipped
  -> failed
```

Each card stores:

- stable card ID;
- candidate identity;
- current state;
- attempt counters by stage;
- last sanitized error and error category;
- replacement lineage;
- validated scene, fact, and image artifacts;
- checkpoint timestamps.

`failed` means the card exhausted its local recovery budget. It does not imply that the production run failed. The orchestrator then attempts replacement or skip.

## Recovery Policy

### Repair

Repair operates on one card and only the invalid stage. Examples include regenerating a missing `factClaim`, reconciling `metricValue` with `verified_value`, correcting a country code, or searching another image source.

### Replace

When repair is exhausted or the subject cannot meet the contract, the orchestrator consumes the next reserve candidate. The replacement starts at content generation and leaves all other cards untouched.

### Skip

When replacement is exhausted, the card becomes `skipped`. A skipped card is excluded from rendering, scene ordering, ranking labels, duration calculation, thumbnail selection, and metadata counts.

Default local budgets are:

| Operation | Maximum attempts |
| --- | ---: |
| Transport call | 3 |
| AI JSON repair | 2 |
| Content repair per card | 2 |
| Fact repair per card | 2 |
| Candidate replacements per card slot | 3 |
| Image strategy | Existing source sequence, once per source strategy |

Budgets must be configurable, bounded, and visible in diagnostics. Exhausting a local budget advances to the next recovery level instead of throwing an unhandled exception.

## Minimum-Card Gate

The run distinguishes desired output from acceptable output:

```text
minimum_cards = max(format_minimum_cards, ceil(target_cards * minimum_card_ratio))
```

The default `minimum_card_ratio` is `0.90`. The existing format-specific minimum remains authoritative when it is higher.

Before rendering:

1. The orchestrator attempts to fill every target slot from the reserve pool.
2. If `ready_cards >= target_cards`, it renders the complete result.
3. If `minimum_cards <= ready_cards < target_cards`, it renders a degraded but valid result.
4. If `ready_cards < minimum_cards`, it requests additional candidates within the run budget.
5. The run fails only when it remains below the minimum after candidate and recovery budgets are exhausted.

For ranking content, remaining cards are sorted and assigned contiguous ranks. Displayed counts and claims must match the actual rendered card count. Non-ranking content is reindexed without introducing rank labels.

Requested duration remains a planning target. The system must not slow animation to hide missing cards. Final duration is derived from the number of ready cards using the established timing model.

## Checkpoint and Resume

Each production run persists a manifest and stage artifacts under its existing production storage boundary. The logical records are:

```text
entity-plan.json
candidate-pool.json
card-states.json
scenes.json
verification.json
images/
render-manifest.json
errors.jsonl
```

Writes use atomic replacement where supported. On restart, the worker loads the manifest, validates artifact references, and resumes the earliest incomplete stage. Ready cards are never regenerated unless the user explicitly requests regeneration.

## Error Classification

### Local recoverable errors

These must not fail a run directly:

- malformed JSON from one AI response;
- incomplete chunk output;
- duplicate or unexpected subject in a chunk;
- missing or invalid field on one card;
- unsupported country code on one card;
- fact confidence below threshold for one card;
- no verified image for one subject;
- exhausted repair budget for a small number of cards.

### Run-level terminal errors

A run may fail only when:

- AI authentication or configuration is invalid;
- required storage or database operations fail persistently;
- the topic or base contract is invalid before card processing;
- ready cards remain below `minimum_cards` after all bounded recovery attempts;
- FFmpeg/rendering fails after its retry policy;
- the run is explicitly cancelled.

All unexpected exceptions are caught at the card, chunk, and run orchestration boundaries. They are classified, logged with context, and converted into controlled state transitions. Programming errors remain visible in structured logs and tests rather than being silently ignored.

## Telegram Experience

Progress messages should report user-facing counts instead of internal IDs:

```text
Preparing content: 58/58
Verified: 54
Repairing: 2
Replaced: 1
Skipped: 1
Images ready: 43/54
```

If degraded rendering is used, completion states the result clearly:

```text
Video completed with 55 of 58 planned cards.
Three cards without reliable data were safely excluded.
```

Technical details remain available in logs and diagnostics, not routine Telegram messages.

## Observability

The run summary records:

- duration of each pipeline stage;
- AI calls, retries, JSON repairs, and token usage where available;
- candidates accepted, rejected, replaced, and skipped;
- failure categories by stage;
- image-source success rates;
- target, minimum, and final card counts;
- whether the run rendered in complete or degraded mode.

These metrics support later tuning without adding channel analytics to this scope.

## Testing Strategy

Unit tests cover candidate normalization, alias deduplication, atomic reserve consumption, partial JSON recovery, card transitions, retry budgets, minimum-card calculations, and rank reconciliation.

Integration tests inject failures into each stage:

- malformed and truncated AI JSON;
- timeout, 429, and 5xx responses;
- missing scenes in one chunk;
- duplicate and unexpected subjects;
- low-confidence facts;
- unavailable images;
- exhausted repair and replacement budgets;
- worker restart after partial completion;
- complete and degraded render paths;
- below-minimum terminal failure.

A production smoke test creates a long video through the Docker and Telegram path, verifies that local failures do not restart completed work, and confirms that the result enters the existing review flow.

## Implementation Boundaries

This work will:

- introduce entity planning and reserve candidates;
- make scene writing operate only on locked subjects;
- add safe AI parsing and bounded recovery;
- add card-level state, replacement, skip, and checkpoint behavior;
- make rendering accept an explicitly valid degraded result;
- improve progress and diagnostics.

This work will not:

- change card or video layouts;
- add channel analytics;
- add n8n;
- redesign image-source ranking;
- modify review approval or YouTube publishing behavior.

## Rollout

The new orchestrator should be introduced behind a configuration flag and enabled first for long celebrity runs. Existing short-run behavior remains available during validation. After unit, integration, Docker, and Telegram smoke tests pass, the resilient path becomes the default and the legacy chunk-selection behavior can be removed in a separate cleanup.
