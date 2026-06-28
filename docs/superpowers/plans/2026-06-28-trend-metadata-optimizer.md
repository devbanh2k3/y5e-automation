# Trend Metadata Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and surface trend/search-optimized metadata variants for each rendered review.

**Architecture:** Add `MetadataOptimizerAgent` as a focused metadata unit. Pipeline calls it after quality gate and before `create_review`. Review storage persists `metadata_variants` and `selected_metadata`; Review UI renders the stored metadata.

**Tech Stack:** Python agents, JSON review artifacts, FastAPI review API, plain JavaScript Review UI, pytest.

---

### Task 1: Metadata Optimizer Agent

**Files:**
- Create: `agents/metadata_optimizer_agent.py`
- Create: `tests/test_metadata_optimizer_agent.py`

- [ ] Test fallback variants include non-`Top 10` titles and score breakdown.
- [ ] Test AI output is normalized to selected metadata and bounded title/tag counts.
- [ ] Implement `MetadataOptimizerAgent.run(content_contract, selected_topic=None)`.

### Task 2: Review Storage

**Files:**
- Modify: `core/reviews.py`
- Modify: `tests/test_reviews.py`

- [ ] Add optional `metadata_variants` and `selected_metadata` to `create_review`.
- [ ] Persist both fields in review JSON.

### Task 3: Pipeline Integration

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `tests/test_pipeline_local_render.py`

- [ ] Call `MetadataOptimizerAgent` before `create_review`.
- [ ] Pass optimized selected metadata into `create_review`.
- [ ] Keep existing `youtube_title`, `youtube_description`, and `youtube_tags` response fields backward-compatible.

### Task 4: Review UI Display

**Files:**
- Modify: `api/static/review-ui.html`
- Modify: `api/static/review-ui.css`
- Modify: `api/static/review-ui.js`
- Modify: `tests/test_api_reviews.py`

- [ ] Display selected metadata.
- [ ] Display title variants with score.
- [ ] Display tags and thumbnail suggestions.

### Task 5: Verification

**Files:**
- Run tests only.

- [ ] Run focused metadata/review/API tests.
- [ ] Run full test suite.
- [ ] Commit.
