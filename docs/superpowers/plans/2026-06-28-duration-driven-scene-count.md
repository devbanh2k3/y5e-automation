# Duration Driven Scene Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--target-duration` increase video length by increasing card/scene count while keeping slide pacing stable.

**Architecture:** Add scene-count planning in `ContentAgent`, pass the required scene count through AI prompt/normalization, and restore fixed render timing in `core.video_contract`. Batch and produce CLIs already pass `duration_target`.

**Tech Stack:** Python agents, Remotion video data contract, pytest.

---

### Task 1: Scene Count Policy

**Files:**
- Modify: `agents/content_agent.py`
- Test: `tests/test_content_agent.py`

- [ ] Add `desired_scene_count_for_duration(duration_target: int) -> int`.
- [ ] Test expected mapping: `40 -> 6`, `60 -> 10`, `90 -> 16`, `120 -> 22`.
- [ ] Use constants: fixed template 8s, 5s/card, clamp 6-24.

### Task 2: AI Contract Scene Count Enforcement

**Files:**
- Modify: `agents/content_agent.py`
- Test: `tests/test_content_agent.py`

- [ ] Pass `desired_scene_count` into `_generate_celebrity_contract_from_topic()`.
- [ ] Update prompt from `Use 8-12 ranking scenes` to exact scene count.
- [ ] Normalize by rejecting fewer scenes and trimming extra scenes to desired count.
- [ ] Test that too few scenes raises `ValueError`.

### Task 3: Stable Render Timing

**Files:**
- Modify: `core/video_contract.py`
- Test: `tests/test_content_contract_v2.py`

- [ ] Remove duration-based `holdDurationFrames` stretching from `build_video_data_from_content_contract()`.
- [ ] Keep `holdDurationFrames = 120` and `transitionDurationFrames = 15`.
- [ ] Replace the previous 90s timing test with a test proving stable hold duration.

### Task 4: Verification

**Files:**
- Run tests only.

- [ ] Run focused tests:
  `python3 -m pytest tests/test_content_agent.py tests/test_content_contract_v2.py tests/test_batch_produce_celebrity_videos.py -q`
- [ ] Run full tests:
  `python3 -m pytest -q`
- [ ] Commit:
  `git add agents/content_agent.py core/video_contract.py tests/test_content_agent.py tests/test_content_contract_v2.py docs/superpowers/specs/2026-06-28-duration-driven-scene-count-design.md docs/superpowers/plans/2026-06-28-duration-driven-scene-count.md`
  `git commit -m "fix: scale target duration with scene count"`
