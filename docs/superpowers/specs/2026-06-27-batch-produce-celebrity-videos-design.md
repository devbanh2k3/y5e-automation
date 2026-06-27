# Batch Produce Celebrity Videos Design

## Goal

Create a small production-facing CLI that produces multiple Celebrity ranking videos in one run and leaves every successful render in `pending_review`.

## Scope

The CLI reuses the existing single-video local render flow from `scripts/produce_celebrity_video.py`. It does not change image selection, rendering templates, topic generation, review storage, upload, or analytics.

## Behavior

- Default command produces 3 videos with `language=en` and `card_layout=flag_hero`.
- Each successful video writes the same artifacts as the single-video script next to the MP4.
- A failed video is recorded in the batch summary and does not stop the rest of the batch.
- `--stop-on-error` stops at the first failed item and returns a non-zero exit code.
- The final stdout payload is JSON with requested count, success count, failure count, each successful review/video path, and each failure error.

## Interfaces

- Script: `scripts/batch_produce_celebrity_videos.py`
- Main command:

```bash
python3 scripts/batch_produce_celebrity_videos.py --count 3 --language en --card-layout flag_hero
```

## Testing

Add focused unit tests that monkeypatch the underlying `produce()` function, proving that the batch runner continues after errors, supports `--stop-on-error`, exposes useful CLI help, and includes review commands in successful item summaries.
