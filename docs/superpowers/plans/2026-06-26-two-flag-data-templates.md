# Two Flag Data Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the current timeline template and add two concise one-card/two-image data-comparison templates.

**Architecture:** Extend the existing video contract with optional secondary image and metric fields, then add two Remotion compositions: `FlagHeroVideo` and `SplitDataVideo`. The Python render path will select a composition from `video_data.template` while preserving `TimelineVideo` as the default.

**Tech Stack:** Python contracts/tests, Remotion React/TypeScript compositions, SVG flag assets under `video_engine/public/images/flags`.

---

### Task 1: Contract Fields and Render Selection

**Files:**
- Modify: `core/video_contract.py`
- Modify: `agents/content_agent.py`
- Modify: `agents/pipeline.py`
- Test: `tests/test_content_contract_v2.py`
- Test: `tests/test_pipeline_local_render.py`

- [ ] Add failing tests for optional fields: `secondaryImagePath`, `countryLabel`, `metricLabel`, `metricValue`.
- [ ] Add failing test that render command chooses `FlagHeroVideo` for `template="flag_hero"`.
- [ ] Implement fields in `build_video_data_from_content_contract`.
- [ ] Implement celebrity country data in `ContentAgent`.
- [ ] Implement composition selection in `_render_local_video`.
- [ ] Run targeted tests.

### Task 2: Remotion Templates

**Files:**
- Modify: `video_engine/src/types/video-data.ts`
- Modify: `video_engine/src/index.tsx`
- Create: `video_engine/src/compositions/FlagHeroVideo.tsx`
- Create: `video_engine/src/compositions/SplitDataVideo.tsx`
- Create: `video_engine/public/images/flags/*.svg`

- [ ] Extend TypeScript `CardData` and `VideoData.template`.
- [ ] Add `FlagHeroVideo` composition: top flag/context image, black rank band, blue name band, metric band, large verified portrait.
- [ ] Add `SplitDataVideo` composition: compact top row with rank/metric, country flag block, large verified portrait.
- [ ] Register both compositions in Remotion.
- [ ] Add minimal SVG flag assets for the current celebrity dataset.
- [ ] Run `npm run build`.

### Task 3: Verification Smoke

**Files:**
- Generated: `output/topics/1/final_video.mp4`
- Generated: `output/topics/1/video_data.json`

- [ ] Run full Python tests.
- [ ] Compile Python modules.
- [ ] Build TypeScript.
- [ ] Render one smoke MP4 using one new template.
- [ ] Confirm output contains new template fields and MP4 metadata is valid.
