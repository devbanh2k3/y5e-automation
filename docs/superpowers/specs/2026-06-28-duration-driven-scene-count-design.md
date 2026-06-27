# Duration Driven Scene Count Design

## Purpose

`--target-duration` must produce a longer video by requesting a suitable number of scenes/cards, not by slowing down the timeline slide speed.

## Decision

Use a fixed production pacing model:

- Hook/outro timing stays controlled by the Remotion template.
- Per-card hold speed stays stable at the existing default pacing.
- Target duration determines the desired scene count.
- AI content generation must be asked for exactly that many scenes.
- The renderer may only use the same stable per-card timing; it must not stretch cards to fill time.

## Scene Count Policy

Use this formula:

```text
desired_scene_count = round((target_duration_seconds - fixed_template_seconds) / seconds_per_card)
```

Production constants:

- `fixed_template_seconds`: 8 seconds
- `seconds_per_card`: 5.0 seconds
- minimum scene count: 6
- maximum scene count: 24

Expected examples:

- 40s -> 6 cards
- 60s -> 10 cards
- 90s -> 16 cards
- 120s -> 22 cards

## Content Agent Behavior

For Celebrity generation, ContentAgent receives `duration_target`, calculates `desired_scene_count`, and instructs the AI to return exactly that number of scenes.

If AI returns a different count:

- fewer scenes: reject the contract so batch retry/replacement can recover.
- more scenes: keep only the requested count if every kept scene is valid.

The seeded fallback contract may repeat its known ranking list only when needed for tests/local fallback, but AI production should prefer unique individual people.

## Render Timing Behavior

`build_video_data_from_content_contract()` must stop stretching `holdDurationFrames` based on duration target. It should use stable default timing:

- `holdDurationFrames = 120`
- `transitionDurationFrames = 15`

This means exact duration comes primarily from scene count.

## Testing

Tests must prove:

- duration targets map to expected scene counts.
- content prompt mentions the exact required scene count.
- AI contract normalization rejects too few scenes.
- video data uses stable hold duration rather than stretched duration.
