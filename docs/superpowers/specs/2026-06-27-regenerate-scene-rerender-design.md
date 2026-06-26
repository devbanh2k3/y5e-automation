# Regenerate Scene Rerender Design

## Goal

When a reviewer rejects a video because one scene has the wrong image, the system regenerates only that scene image, rebuilds the video payload, renders a new MP4, and returns the same review to `pending_review`.

## Scope

This step only supports `wrong_image` scene regeneration for local celebrity renders. It does not add UI, upload, analytics, partial MP4 stitching, text regeneration, metric regeneration, or layout regeneration.

## Flow

1. Load the existing review by `review_id`.
2. Validate `content_contract.scenes`, `image_verification_contract.items`, and `topic_id`.
3. Run `RealImageAgent` for the selected scene only.
4. Replace only the selected image verification item.
5. Rebuild `video_data` from the full content contract.
6. Apply the full updated image verification contract to `video_data`.
7. Render a new MP4 using the existing local Remotion renderer.
8. Update the review video path and status back to `pending_review`.
9. Append `scene_regenerated` and `video_rerendered` events.

## Output Rules

The rerender writes a versioned MP4 path instead of overwriting the previous approved artifact. The review points to the newest MP4 so CLI/API review consumers always open the current candidate.

## Error Handling

If the updated image contract is not fully verified, rerender stops before calling Remotion. If render fails, the regenerated image data should not be presented as a completed review candidate.

## Tests

Tests must prove that only the selected image changes, rerender is called with updated `video_data`, review status is `pending_review`, the video path changes to the rerendered MP4, and CLI supports disabling rerender for isolated image repair.
