# Regenerate Scene Rerender Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect wrong-image scene regeneration to local MP4 rerender so review returns to a fresh `pending_review` video candidate.

**Architecture:** Keep the orchestration in `scripts/regenerate_scene.py` because this is currently the review repair CLI boundary. Reuse `build_video_data_from_content_contract`, `apply_verified_images_to_video_data`, `validate_video_data`, and `Pipeline._render_local_video` rather than duplicating render logic.

**Tech Stack:** Python async CLI, JSON review store, Remotion local renderer, pytest.

---

### Task 1: Failing Tests

**Files:**
- Modify: `tests/test_regenerate_scene_cli.py`

- [ ] Add a test that monkeypatches `RealImageAgent` and `Pipeline._render_local_video`, calls `regenerate_wrong_image_scene(..., rerender=True)`, and asserts the selected image changes, render receives updated card image paths, review status is `pending_review`, video path is updated, and `video_rerendered` is appended.
- [ ] Add a test that calls `regenerate_wrong_image_scene(..., rerender=False)` and asserts render is not called.
- [ ] Run `python3 -m pytest tests/test_regenerate_scene_cli.py -q` and confirm the new rerender test fails because the function does not accept `rerender`.

### Task 2: Implementation

**Files:**
- Modify: `scripts/regenerate_scene.py`

- [ ] Import `Pipeline` and video contract helpers.
- [ ] Extend `regenerate_wrong_image_scene` with `rerender: bool = True`.
- [ ] After replacing the image contract, rebuild video data from the full content contract and updated image contract.
- [ ] When `rerender` is enabled, call `Pipeline()._render_local_video(topic_id=topic_id, video_data=video_data)`.
- [ ] Update `review["video"]["file_path"]`, `video_id`, and status to `pending_review`.
- [ ] Append `video_rerendered` event with the same scene and reason.
- [ ] Add CLI flag `--no-rerender` for image-only repair.

### Task 3: Verification and Commit

**Files:**
- Modified tests and implementation files.

- [ ] Run `python3 -m pytest tests/test_regenerate_scene_cli.py -q`.
- [ ] Run `python3 -m pytest tests/test_reviews.py tests/test_review_video_cli.py tests/test_api_reviews.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Commit the spec, plan, tests, and implementation.
