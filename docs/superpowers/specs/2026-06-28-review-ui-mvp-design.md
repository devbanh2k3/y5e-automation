# Review UI MVP Design

## Purpose

Review UI MVP gives local production operators a browser page to review rendered videos without reading JSON or copying long CLI commands for every decision.

## Scope

Build a local-only FastAPI UI at `/review-ui` using the existing review JSON store and review API.

The MVP includes:

- pending review list
- review detail panel
- video preview
- scene/card list
- image verification source/license/attribution display
- quality gate summary
- approve action
- reject action with reason, scene indexes, and notes
- regenerate-scene command display for copied CLI execution

The MVP does not include auth, YouTube upload, analytics, n8n orchestration, or direct regenerate execution.

## Architecture

Use the existing FastAPI app:

- `GET /review-ui` serves a static HTML shell.
- `/static/review-ui.css` and `/static/review-ui.js` serve UI assets.
- Existing `/api/reviews` endpoints provide review data and approve/reject transitions.
- New `GET /api/reviews/{review_id}/video` streams the MP4 from the review artifact `video.file_path`.

The video endpoint only serves existing files referenced by a review artifact. It returns 404 when the review or file is missing.

## UI Flow

1. Load pending reviews from `/api/reviews?status=pending_review&limit=50`.
2. Select the first review by default.
3. Fetch full detail from `/api/reviews/{review_id}`.
4. Render video preview from `/api/reviews/{review_id}/video`.
5. Render scene cards using `content_contract.scenes`.
6. Match image verification items by `scene_index`.
7. Approve posts to `/api/reviews/{review_id}/approve`.
8. Reject posts to `/api/reviews/{review_id}/reject`.
9. After approve/reject, refresh the pending list.

## Testing

Tests cover:

- `/review-ui` returns HTML with the app mount point.
- static UI JavaScript is reachable.
- video endpoint serves the review MP4 bytes.
- video endpoint returns 404 when the referenced file is missing.
