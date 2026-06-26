# Timeline Hook 12s Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first timeline hook show the first 3 cards as three sequential 4-second slots: 2 seconds slide-up and 2 seconds settled.

**Architecture:** Keep the existing `TimelineVideo` composition and card components. Replace the current staggered-overlap hook timing with a slot-based hook phase where only one of the first three cards appears per 4-second slot, then continue into the existing morph and main scroll phases.

**Tech Stack:** Remotion, React, TypeScript, pytest source contract test, `npm run build`.

---

### Task 1: Hook Timing Contract

**Files:**
- Test: `tests/test_timeline_hook_timing.py`
- Modify: `video_engine/src/compositions/TimelineVideo.tsx`

- [ ] **Step 1: Write the failing test**

Create `tests/test_timeline_hook_timing.py`:

```python
from pathlib import Path


TIMELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "video_engine"
    / "src"
    / "compositions"
    / "TimelineVideo.tsx"
)


def test_timeline_hook_uses_three_sequential_four_second_slots() -> None:
    source = TIMELINE_PATH.read_text()

    assert "const HOOK_CARD_SLOT = 120;" in source
    assert "const HOOK_SLIDE_IN = 60;" in source
    assert "const HOOK_SETTLE = HOOK_CARD_SLOT - HOOK_SLIDE_IN;" in source
    assert "const hookEnd = hookCardCount * HOOK_CARD_SLOT;" in source
    assert "const activeHookCardIndex = Math.min(" in source
    assert "if (isHook && index !== activeHookCardIndex) return null;" in source
    assert "index * HOOK_CARD_SLOT" in source
    assert "HOOK_STAGGER" not in source
    assert "HOOK_HOLD" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_timeline_hook_timing.py -q`

Expected: FAIL because `HOOK_CARD_SLOT` and sequential hook logic do not exist yet.

- [ ] **Step 3: Implement minimal hook timing change**

In `video_engine/src/compositions/TimelineVideo.tsx`:

```ts
const HOOK_CARDS = 3;
const HOOK_CARD_SLOT = 120;    // 4s per hook card at 30fps
const HOOK_SLIDE_IN = 60;      // 2s slide up animation
const HOOK_SETTLE = HOOK_CARD_SLOT - HOOK_SLIDE_IN; // 2s settled read time
const MORPH_FRAMES = 30;       // 1s morph to scroll
```

Replace hook phase timing with:

```ts
const hookEnd = hookCardCount * HOOK_CARD_SLOT;
const morphEnd = hookEnd + MORPH_FRAMES;
const activeHookCardIndex = Math.min(
  hookCardCount - 1,
  Math.floor(frame / HOOK_CARD_SLOT)
);
```

Render only the active hook card during hook:

```ts
if (isHook && index !== activeHookCardIndex) return null;
```

Compute local hook animation from each card slot:

```ts
const cardStart = index * HOOK_CARD_SLOT;
const localFrame = Math.max(0, frame - cardStart);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_timeline_hook_timing.py -q`

Expected: PASS.

- [ ] **Step 5: Verify video engine build**

Run: `npm run build` from `video_engine`.

Expected: TypeScript build passes.

- [ ] **Step 6: Run focused Python regression tests**

Run: `python3 -m pytest tests/test_video_contract_local_render.py tests/test_pipeline_local_render.py -q`

Expected: PASS.
