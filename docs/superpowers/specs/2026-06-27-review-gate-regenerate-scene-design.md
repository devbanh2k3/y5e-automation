# Review Gate CLI + Regenerate Scene MVP Design

## Goal

Build a practical review loop for rendered videos before upload: list pending reviews, inspect artifacts, approve good videos, reject bad videos with structured reasons, and regenerate a single bad scene/card when the issue is a wrong celebrity image.

This scope intentionally stops before analytics and upload. The output of this feature is a controlled local workflow for improving generated videos until they are approved.

## Current Context

The project already has a JSON-backed review store in `core/reviews.py` with these states:

- `pending_review`
- `approved`
- `rejected`

The API already exposes review list/detail/approve/reject endpoints. Local render creates a review after MP4 render. Recent production smoke produced a review with:

- `content_contract`
- `image_verification_contract`
- rendered `video.file_path`
- YouTube metadata

The missing production behavior is structured rejection data and a CLI workflow that can be used without manually editing JSON files.

## Non-Goals

This feature will not upload videos to YouTube.

This feature will not build a web UI.

This feature will not implement channel analytics.

This feature will not fully regenerate text/layout yet. It will store structured reasons for `bad_text` and `bad_layout`, but the first executable regeneration path is `wrong_image` for a single scene.

## Review Data Model

Existing review JSON remains backward-compatible. New fields are additive:

```json
{
  "reject_reason": "wrong_image",
  "rejected_scenes": [5],
  "review_events": [
    {
      "event": "rejected",
      "reason": "wrong_image",
      "scenes": [5],
      "notes": "Madonna image is wrong",
      "created_at": "2026-06-27T00:00:00+00:00"
    }
  ]
}
```

Allowed reject reasons:

- `wrong_image`
- `bad_text`
- `bad_layout`
- `bad_topic`
- `bad_metric`
- `other`

`approve_review()` will append an `approved` event. `reject_review()` will require a non-empty reason and append a `rejected` event.

A review can only transition from `pending_review` to `approved` or `rejected`. Existing non-pending guard remains unchanged.

## CLI Design

Create `scripts/review_video.py`.

Commands:

```bash
python3 scripts/review_video.py list --status pending_review --limit 10
python3 scripts/review_video.py show REVIEW_ID
python3 scripts/review_video.py approve REVIEW_ID --notes "looks good"
python3 scripts/review_video.py reject REVIEW_ID --reason wrong_image --scene 5 --notes "wrong person image"
```

Behavior:

- `list` prints compact JSON summaries: review id, status, title, topic id, video path, created time.
- `show` prints the full review JSON.
- `approve` marks a pending review approved and prints the updated status.
- `reject` marks a pending review rejected, stores structured reason/scene data, and prints the updated status.

The CLI will use `core.reviews` directly instead of calling the HTTP API. This keeps it reliable for local production smoke and avoids requiring API availability for review operations.

## Regenerate Scene MVP

Create `scripts/regenerate_scene.py`.

MVP command:

```bash
python3 scripts/regenerate_scene.py REVIEW_ID --scene 5 --reason wrong_image
```

Behavior for `wrong_image`:

1. Load the review by id.
2. Validate that `scene` is an integer index inside `content_contract.scenes`.
3. Build a one-scene temporary content contract using the selected scene.
4. Run `RealImageAgent.run_for_content_contract()` for that one scene with `strict=True`.
5. Replace only the selected item in the original `image_verification_contract.items`.
6. Preserve all other scene data and all other image items.
7. Append a `scene_regenerated` event to `review_events`.
8. Save the updated review JSON.

The script will not rerender the MP4 in this MVP. It updates the review artifact so a later rerender step can reuse the corrected `image_verification_contract`.

If the reason is not `wrong_image`, the script exits with a clear error explaining that only wrong-image regeneration is supported in this MVP.

## Error Handling

Review CLI errors:

- Unknown review id exits non-zero with `Review <id> not found`.
- Approving/rejecting a non-pending review exits non-zero with the existing `review is not pending` message.
- Reject without reason exits non-zero.
- Reject with invalid reason exits non-zero and prints allowed values.

Regenerate errors:

- Unknown review id exits non-zero.
- Missing `content_contract.scenes` exits non-zero.
- Scene index out of range exits non-zero.
- Unsupported reason exits non-zero.
- Real image verification failure exits non-zero and leaves the original review unchanged.

## Testing

Add focused tests before implementation:

- `tests/test_reviews.py`
  - reject stores `reject_reason`, `rejected_scenes`, and event history.
  - approve appends event history.
  - invalid reject reason is rejected.

- `tests/test_review_video_cli.py`
  - `list` prints pending review summary.
  - `show` prints full review JSON.
  - `approve` updates status.
  - `reject` stores structured reason and scene.

- `tests/test_regenerate_scene_cli.py`
  - wrong-image regeneration replaces only one image item.
  - unsupported reason exits non-zero.
  - out-of-range scene exits non-zero.

Run verification:

```bash
python3 -m pytest tests/test_reviews.py tests/test_review_video_cli.py tests/test_regenerate_scene_cli.py -q
python3 -m pytest -q
```

## Success Criteria

The feature is complete when:

1. A rendered pending review can be listed and shown from CLI.
2. A pending review can be approved from CLI.
3. A pending review can be rejected with a structured reason and scene index.
4. A single wrong-image scene can be regenerated without changing unrelated scenes.
5. Existing API review behavior remains compatible.
6. Full test suite passes.
