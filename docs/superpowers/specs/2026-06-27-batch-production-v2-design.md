# Batch Production v2 Design

## Purpose

Batch Production v2 turns the current successful one-video pipeline into a controlled production run. A batch request should try to produce the requested number of pending-review Celebrity videos, automatically classify common failures, apply bounded recovery, and report whether the run filled the requested count.

This feature does not upload to YouTube and does not add channel analytics. It stays focused on producing reviewable MP4 artifacts reliably.

## User Goals

- Run one command to request multiple videos.
- Avoid stopping on common AI/content/fact failures.
- Replace rejected topics until the requested count is filled or the attempt budget is exhausted.
- Control target video duration from the batch command.
- See a practical summary with produced videos, failed attempts, replacement count, unfilled count, review IDs, video paths, and next review commands.

## CLI

The main command remains:

```bash
python3 scripts/batch_produce_celebrity_videos.py --count 10 --language en --card-layout flag_hero
```

New options:

```bash
--max-attempts 30
--duration-profile short|standard|long
--target-duration 60
```

Defaults:

- `--max-attempts`: `count * 3`
- `--duration-profile`: `standard`
- `--target-duration`: derived from the profile unless explicitly provided

Duration profiles:

- `short`: target 40 seconds, acceptable range 35-45 seconds
- `standard`: target 60 seconds, acceptable range 55-70 seconds
- `long`: target 90 seconds, acceptable range 80-100 seconds

If both `duration_profile` and `target_duration` are passed, `target_duration` wins while `duration_profile` is still reported for context.

## Production Loop

Batch v2 selects an initial slate, then processes attempts until either:

- `success_count == requested_count`, or
- `attempted_count == max_attempts`, or
- topic selection can no longer provide replacements.

Every production attempt has:

- a stable `attempt_index`
- optional `batch_slot` for the requested output slot
- selected topic reservation ID
- attempt type: `initial`, `retry_same_topic`, or `replacement`
- final status: `produced`, `failed`, or `recovered`

The batch must mark every failed reservation as failed in topic history and mark every produced reservation as produced.

## Failure Classification

Batch v2 classifies exceptions into stable categories:

- `repairable_contract`: `VideoContractError` caused by missing `factClaim`, missing fact fields, unsupported country code, missing country code, or required scene/card fields.
- `fact_rejected`: `FactVerificationError`, especially confidence below `0.80` or rejected fact status.
- `image_failed`: image verification or real-image acquisition failures.
- `render_failed`: Remotion/local render failures.
- `topic_selection_failed`: `TopicSelectionError` while selecting initial slate or replacement.
- `unknown`: any unclassified exception.

The summary must include both `error_type` and `classification`.

## Recovery Policy

Recovery is deliberately bounded to avoid wasting quota:

- `repairable_contract`: retry the same topic once. This gives ContentAgent one fresh chance to emit a valid contract.
- `fact_rejected`: do not retry the same topic. Mark failed and request replacement.
- `image_failed`: request replacement in v2. Scene-level image repair remains a separate review/regenerate workflow.
- `render_failed`: retry the same topic once.
- `unknown`: request replacement unless `--stop-on-error` is set.
- `topic_selection_failed`: record failure and stop replacement attempts.

Each failure record includes `recovery_action`:

- `retry_same_topic`
- `request_replacement`
- `stop_on_error`
- `no_replacement_available`
- `attempt_budget_exhausted`

## Duration Flow

Duration settings flow through:

```text
batch CLI -> produce() -> Pipeline.run_local_render() -> ContentAgent.run() -> content contract -> video_data/render summary
```

The ContentAgent receives `duration_target` and writes it into `duration_target` in the content contract. Rendering already computes actual duration from frame data; batch summary reports `actual_duration_sec` from the produced result.

Batch v2 must not require exact output duration because Remotion timing depends on card count and template timing. It only records target and actual values for operational review.

## Summary Shape

Batch output adds these fields:

```json
{
  "status": "completed",
  "requested_count": 10,
  "success_count": 10,
  "attempted_count": 16,
  "max_attempts": 30,
  "replacement_count": 6,
  "retry_count": 2,
  "unfilled_count": 0,
  "duration_profile": "standard",
  "target_duration": 60,
  "items": [],
  "failures": []
}
```

Status values:

- `completed`: requested count filled and no terminal unfilled outputs.
- `completed_with_recoveries`: requested count filled but failures/retries/replacements occurred.
- `incomplete`: attempt budget or topic exhaustion prevented filling the requested count.
- `stopped_on_error`: `--stop-on-error` stopped the run.

Failure records include:

```json
{
  "attempt_index": 3,
  "batch_slot": 2,
  "reservation_id": "reservation-id",
  "title": "Topic title",
  "error": "all facts must be AI verified with confidence >= 0.80",
  "error_type": "FactVerificationError",
  "classification": "fact_rejected",
  "recovery_action": "request_replacement",
  "final_status": "failed"
}
```

Successful item records include duration metadata:

```json
{
  "batch_index": 4,
  "attempt_type": "replacement",
  "review_id": "review-id",
  "video_path": "/path/final_video.mp4",
  "duration_profile": "standard",
  "target_duration": 60,
  "actual_duration_sec": 64
}
```

## Testing Strategy

Tests use fake strategies and fake `produce()` functions so they do not call AI, image search, or Remotion.

Required coverage:

- failure classification for contract, fact, image, render, topic selection, and unknown errors.
- batch fills requested count using replacements until success count equals count.
- max attempts prevents runaway replacement loops.
- repairable contract retries same topic once before replacement.
- duration profile and target duration pass through `batch -> produce`.
- CLI parses `--max-attempts`, `--duration-profile`, and `--target-duration`.
- existing behavior with `--stop-on-error` remains supported.

## Out of Scope

- YouTube upload.
- Analytics-based topic learning.
- Human review UI.
- Scene-level regeneration from inside the batch loop.
- Forcing exact output duration at the renderer level.
