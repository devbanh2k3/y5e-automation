# Batch Produce Celebrity Videos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLI that produces multiple Celebrity videos into pending review using the existing single-video production path.

**Architecture:** The new batch script imports `produce()` from `scripts.produce_celebrity_video` and wraps it in a loop. It returns structured JSON so the user can immediately review, approve, reject, or regenerate each video.

**Tech Stack:** Python async CLI, argparse, pytest, existing local render pipeline.

---

### Task 1: Batch Runner Tests

**Files:**
- Create: `tests/test_batch_produce_celebrity_videos.py`

- [ ] Write tests for successful multiple-item batch output.
- [ ] Write tests for continuing after one failure.
- [ ] Write tests for `--stop-on-error`.
- [ ] Write tests for CLI help.

### Task 2: Batch Runner Script

**Files:**
- Create: `scripts/batch_produce_celebrity_videos.py`

- [ ] Implement `produce_batch()`.
- [ ] Implement JSON summary output.
- [ ] Implement CLI args: `--count`, `--language`, `--card-layout`, `--no-write-artifacts`, `--stop-on-error`.
- [ ] Return exit code 0 when at least one video succeeds unless `--stop-on-error` stops on a failure.

### Task 3: Verification

- [ ] Run `python3 -m pytest tests/test_batch_produce_celebrity_videos.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Commit the feature.
