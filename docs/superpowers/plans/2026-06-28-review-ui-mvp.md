# Review UI MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local browser review UI for pending rendered videos.

**Architecture:** Extend the existing FastAPI app with static UI files and a video streaming endpoint. Reuse existing review JSON storage and approve/reject API.

**Tech Stack:** FastAPI, plain HTML/CSS/JavaScript, pytest/httpx.

---

### Task 1: UI and Video Endpoint Tests

**Files:**
- Modify: `tests/test_api_reviews.py`

- [ ] Add tests for `/review-ui`, `/static/review-ui.js`, `/api/reviews/{review_id}/video`, and missing video 404.

### Task 2: FastAPI Routes

**Files:**
- Modify: `api/main.py`

- [ ] Mount static assets from `api/static`.
- [ ] Add `GET /review-ui`.
- [ ] Add `GET /api/reviews/{review_id}/video`.

### Task 3: Static UI

**Files:**
- Create: `api/static/review-ui.html`
- Create: `api/static/review-ui.css`
- Create: `api/static/review-ui.js`

- [ ] Build a compact local review interface with list, video, scene cards, approve, reject, and regenerate command display.

### Task 4: Verification

**Files:**
- Run tests only.

- [ ] Run `python3 -m pytest tests/test_api_reviews.py -q`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Commit the feature.
