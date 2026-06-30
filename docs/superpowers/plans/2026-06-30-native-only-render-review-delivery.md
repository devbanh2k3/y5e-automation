# Native-Only Render and Review Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require native hardware rendering, loop short background music through the full video, and improve review downloads and tag copying.

**Architecture:** Keep Docker as the application control plane but make the render selector fail closed whenever native rendering cannot complete. Add looping at the Remotion composition layer, derive a safe response filename at the review API boundary, and expose selected tags as one CSV value in Review UI and Telegram review listings.

**Tech Stack:** Python 3.11, FastAPI/Starlette, pytest, TypeScript/React, Remotion, Vitest, vanilla Review UI JavaScript, Telegram Bot API.

---

## File Map

- `core/config.py`: validate the native fallback policy.
- `.env.example`: document native-only production configuration.
- `agents/pipeline.py`: remove runtime Docker fallback when native rendering is enabled.
- `tests/test_pipeline_local_render.py`: prove native failures cannot invoke Docker.
- `video_engine/src/compositions/RankingVideo.tsx`: loop ranking background audio.
- `video_engine/src/compositions/TimelineVideo.tsx`: loop timeline background audio.
- `video_engine/src/compositions/ComparisonVideo.tsx`: loop comparison background audio.
- `video_engine/src/compositions/audio-loop.test.ts`: enforce looping across all compositions.
- `api/main.py`: derive safe title-based MP4 response filenames.
- `tests/test_api_reviews.py`: cover filename safety and inline playback.
- `api/static/review-ui.html`: add a dedicated copyable tags control.
- `api/static/review-ui.js`: render and copy CSV tags.
- `api/static/review-ui.css`: style the tags copy row without changing the page structure.
- `services/telegram_remote.py`: include copy-friendly comma-separated tags in pending review output.
- `tests/test_telegram_remote.py`: verify selected tag precedence and formatting.

### Task 1: Enforce Native-Only Rendering

**Files:**
- Modify: `core/config.py`
- Modify: `.env.example`
- Modify: `agents/pipeline.py:841-928`
- Test: `tests/test_pipeline_local_render.py`

- [ ] **Step 1: Write failing tests for missing runner and failed native job**

Add tests that set `NATIVE_RENDER_ENABLED=true` and `NATIVE_RENDER_FALLBACK=error`, replace `_render_local_video` with a function that raises `AssertionError`, and assert:

```python
with pytest.raises(RuntimeError, match="no live native render runner"):
    await Pipeline()._render_video(
        topic_id=42,
        video_data=_minimal_video_data(target_duration=300),
    )
```

For a claimed job returning `NativeRenderResult(status="failed", message="encoder failed")`, assert:

```python
with pytest.raises(RuntimeError, match="encoder failed"):
    await Pipeline()._render_video(
        topic_id=42,
        video_data=_minimal_video_data(target_duration=300),
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest tests/test_pipeline_local_render.py -k "native and (runner or failed)" -v
```

Expected: at least one test fails because the current pipeline can call `_render_docker_fallback` when fallback is `docker`, or because the error text is not the required native-runner message.

- [ ] **Step 3: Implement fail-closed native selection**

In `agents/pipeline.py`, make `_render_video` follow this rule:

```python
if not settings.native_render_enabled:
    result = await self._render_docker_fallback(...)
    return {**result, "renderer": "docker"}

if not await render_queue.has_live_runner():
    raise RuntimeError(
        "no live native render runner is available; start scripts/native_render_runner.py"
    )

# enqueue and wait for native result
if result.status != "completed":
    raise RuntimeError(result.message or result.error_code or "native render failed")
```

Remove both Docker fallback branches from the native-enabled path. Keep explicit Docker rendering only when `NATIVE_RENDER_ENABLED=false` for development compatibility.

In `core/config.py`, change the default to:

```python
native_render_fallback: str = "error"
```

Add a validator accepting only `error` and legacy `docker`, while production behavior and examples use `error`. Update `.env.example`:

```dotenv
NATIVE_RENDER_ENABLED=true
NATIVE_RENDER_FALLBACK=error
```

- [ ] **Step 4: Run focused and configuration tests**

Run:

```bash
pytest tests/test_pipeline_local_render.py tests/test_config_validation.py -v
```

Expected: PASS. Existing explicit development fallback tests may be updated to assert Docker is used only when native rendering is disabled.

- [ ] **Step 5: Commit the native-only change**

```bash
git add core/config.py .env.example agents/pipeline.py tests/test_pipeline_local_render.py tests/test_config_validation.py
git commit -m "fix: require native hardware rendering"
```

### Task 2: Loop Background Music in Every Composition

**Files:**
- Create: `video_engine/src/compositions/audio-loop.test.ts`
- Modify: `video_engine/src/compositions/RankingVideo.tsx`
- Modify: `video_engine/src/compositions/TimelineVideo.tsx`
- Modify: `video_engine/src/compositions/ComparisonVideo.tsx`

- [ ] **Step 1: Write a failing source-contract test**

Create `audio-loop.test.ts` that reads the three composition source files and requires the music audio element to include `loop`:

```ts
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {describe, expect, it} from "vitest";

const files = ["RankingVideo.tsx", "TimelineVideo.tsx", "ComparisonVideo.tsx"];

describe("background audio", () => {
  for (const file of files) {
    it(`loops music in ${file}`, () => {
      const source = readFileSync(join(__dirname, file), "utf8");
      expect(source).toMatch(/<Audio[\s\S]*?src=\{staticFile\(musicPath\)\}[\s\S]*?\bloop\b[\s\S]*?\/>/);
    });
  }
});
```

- [ ] **Step 2: Run Vitest and verify RED**

Run:

```bash
cd video_engine && npm test -- --run src/compositions/audio-loop.test.ts
```

Expected: three failures because the current `Audio` elements do not include `loop`.

- [ ] **Step 3: Add looping to the three music elements**

Use the Remotion `Audio` loop prop consistently:

```tsx
{musicPath && (
  <Audio src={staticFile(musicPath)} volume={0.3} loop />
)}
```

Do not add FFmpeg preprocessing, duplicate the track, or change volume.

- [ ] **Step 4: Run render-engine tests and build**

Run:

```bash
cd video_engine && npm test -- --run && npm run build
```

Expected: all tests pass and the Remotion bundle builds successfully.

- [ ] **Step 5: Commit the audio loop change**

```bash
git add video_engine/src/compositions/RankingVideo.tsx video_engine/src/compositions/TimelineVideo.tsx video_engine/src/compositions/ComparisonVideo.tsx video_engine/src/compositions/audio-loop.test.ts
git commit -m "fix: loop background music through video"
```

### Task 3: Use the Video Title as the Review Download Filename

**Files:**
- Modify: `api/main.py:371-389`
- Test: `tests/test_api_reviews.py`

- [ ] **Step 1: Write failing API tests**

Create a temporary MP4 and mock `get_review` with selected title `Top 10: Stars / 2026?`. Assert:

```python
response = await client.get("/api/reviews/review-1/video")

assert response.status_code == 200
assert response.headers["content-type"].startswith("video/mp4")
assert response.headers["content-disposition"].startswith("inline;")
assert "Top 10 Stars 2026.mp4" in response.headers["content-disposition"]
```

Add parameterized unit cases for the filename helper:

```python
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Top 10: Stars / 2026?", "Top 10 Stars 2026.mp4"),
        ("CON", "video.mp4"),
        ("", "video.mp4"),
    ],
)
def test_review_video_filename_is_cross_platform_safe(title, expected):
    assert review_video_filename(title) == expected
```

- [ ] **Step 2: Run the API tests and verify RED**

Run:

```bash
pytest tests/test_api_reviews.py -k "video_filename or review_video" -v
```

Expected: FAIL because the endpoint currently returns the stored `final_video.mp4` basename and the helper does not exist.

- [ ] **Step 3: Implement safe filename normalization**

Add a small public helper in `api/main.py` (or a focused module if imports become cyclic):

```python
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

def review_video_filename(title: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(title or ""))
    value = " ".join(value.split()).strip(" .")
    value = value[:120].rstrip(" .")
    if not value or value.upper() in WINDOWS_RESERVED_NAMES:
        value = "video"
    return f"{value}.mp4"
```

Resolve title in this order: `selected_metadata.title`, `youtube.title`, `content_contract.youtube_title`, `content_contract.title`. Pass the result to `FileResponse(filename=..., content_disposition_type="inline")`.

- [ ] **Step 4: Run all API review tests**

Run:

```bash
pytest tests/test_api_reviews.py -v
```

Expected: PASS, including 404 and inline preview behavior.

- [ ] **Step 5: Commit the filename change**

```bash
git add api/main.py tests/test_api_reviews.py
git commit -m "feat: name review downloads from video title"
```

### Task 4: Add Copy-Friendly CSV Tags to Review UI and Telegram

**Files:**
- Modify: `api/static/review-ui.html`
- Modify: `api/static/review-ui.js`
- Modify: `api/static/review-ui.css`
- Modify: `services/telegram_remote.py`
- Test: `tests/test_api_reviews.py`
- Test: `tests/test_telegram_remote.py`

- [ ] **Step 1: Write failing Review UI and Telegram tests**

Extend the static UI test to assert:

```python
assert 'id="metadataTagsCsv"' in html_response.text
assert 'id="copyTagsButton"' in html_response.text
assert "navigator.clipboard.writeText" in js_response.text
assert "join(\", \"" in js_response.text
```

Add a Telegram review test where `get_review` returns:

```python
{
    "selected_metadata": {"tags": ["celebrity", "richest singers", "2026"]},
    "youtube": {"title": "Richest Singers", "tags": ["fallback"]},
}
```

Assert the response contains exactly:

```text
celebrity, richest singers, 2026
```

and does not contain `#celebrity` or `fallback`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest tests/test_api_reviews.py tests/test_telegram_remote.py -k "tags or review_ui" -v
```

Expected: failures because the dedicated CSV field, copy button, and Telegram tag line do not exist.

- [ ] **Step 3: Implement the Review UI CSV field and copy action**

Replace the visual tag chip area with a dedicated row while retaining the existing metadata section:

```html
<div class="copy-field">
  <code id="metadataTagsCsv" class="copy-value"></code>
  <button id="copyTagsButton" type="button">Copy tags</button>
</div>
```

In `review-ui.js`, select both elements and add:

```js
function selectedTags(review) {
  const variants = review.metadata_variants || {};
  const selected = review.selected_metadata || variants.selected_metadata || {};
  const values = selected.tags || review.youtube?.tags || variants.tags || [];
  return Array.isArray(values) ? values.map((value) => text(value).trim()).filter(Boolean) : [];
}

function renderTagCsv(review) {
  const value = selectedTags(review).join(", ");
  els.metadataTagsCsv.textContent = value || "No tags";
  els.copyTagsButton.disabled = !value;
  els.copyTagsButton.dataset.copyValue = value;
}
```

Bind the click handler:

```js
els.copyTagsButton.addEventListener("click", async () => {
  const value = els.copyTagsButton.dataset.copyValue || "";
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    els.copyTagsButton.textContent = "Copied";
  } catch (_error) {
    alert("Could not copy tags. Select the tag text and copy it manually.");
  }
});
```

Add restrained CSS for `.copy-field` and `.copy-value`; preserve selectable text and responsive wrapping.

- [ ] **Step 4: Add CSV tags to Telegram pending reviews**

Extend `_review_display_title` into a review display helper returning title and tags, or add `_review_display_tags(review_id)`. Select tags from `selected_metadata.tags` first, then `youtube.tags`, normalize whitespace, and join with `, `.

Append beneath each review title:

```python
if tags_csv:
    lines.append(f"   Tags: `{tags_csv}`")
```

Keep review IDs hidden and preserve owner-scoped `list_pending_review_tasks` behavior.

- [ ] **Step 5: Run UI and Telegram tests**

Run:

```bash
pytest tests/test_api_reviews.py tests/test_telegram_remote.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the copy-friendly tags change**

```bash
git add api/static/review-ui.html api/static/review-ui.js api/static/review-ui.css services/telegram_remote.py tests/test_api_reviews.py tests/test_telegram_remote.py
git commit -m "feat: add copy-friendly review tags"
```

### Task 5: Integrated Verification

**Files:**
- Verify only; no new production behavior.

- [ ] **Step 1: Run backend regression tests**

```bash
pytest tests/test_pipeline_local_render.py tests/test_config_validation.py tests/test_api_reviews.py tests/test_telegram_remote.py -v
```

Expected: PASS.

- [ ] **Step 2: Run Remotion tests and build**

```bash
cd video_engine && npm test -- --run && npm run build
```

Expected: PASS with a successful bundle.

- [ ] **Step 3: Verify configuration and source policy**

```bash
rg -n "NATIVE_RENDER_ENABLED|NATIVE_RENDER_FALLBACK" .env.example
rg -n "using Docker fallback" agents/pipeline.py
```

Expected: `.env.example` shows `true` and `error`; the second command returns no native fallback log line.

- [ ] **Step 4: Recreate application services without starting a Docker renderer**

```bash
docker compose up -d --build api worker telegram-bot
```

Expected: control-plane services are healthy. The host native runner remains a separate host process and must report a live heartbeat before production jobs are accepted.

- [ ] **Step 5: Perform a short production smoke test**

Create one short video from Telegram or the existing CLI. Confirm logs identify `renderer=native`, background music is audible near the final frame, Review UI copies comma-separated tags, and the review endpoint downloads with the title-based filename.

- [ ] **Step 6: Record final status**

```bash
git status --short
git log -5 --oneline
```

Expected: only pre-existing unrelated worktree changes remain; the implementation commits are visible.
