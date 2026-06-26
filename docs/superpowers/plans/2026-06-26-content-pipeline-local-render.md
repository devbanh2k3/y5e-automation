# Content Pipeline Local Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `local_render` pipeline mode that produces a local video artifact summary without uploading to YouTube.

**Architecture:** `PipelineMode.LOCAL_RENDER` is accepted by the API and routed by the worker to `Pipeline.run_local_render`. The local render pipeline builds a minimal Remotion-compatible payload through a focused contract module, delegates rendering through an injectable renderer method, and returns a structured summary that the worker stores in Redis `result_summary`.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, Redis asyncio, Remotion data JSON, pytest, pytest-asyncio.

---

## File Map

- Modify `core/job_models.py`: add `PipelineMode.LOCAL_RENDER`.
- Modify `api/main.py`: `local_render` becomes valid automatically through `PipelineMode`; update endpoint tests.
- Create `core/video_contract.py`: validate and build local render Remotion input.
- Modify `agents/pipeline.py`: add `run_local_render` and injectable `_render_local_video` helper.
- Modify `workers/pipeline_worker.py`: route `local_render` jobs to `run_local_render`.
- Modify `README.md`: document local render mode.
- Modify tests: `tests/test_api_jobs.py`, `tests/test_pipeline_worker.py`.
- Add tests: `tests/test_video_contract_local_render.py`, `tests/test_pipeline_local_render.py`.

---

### Task 1: Add Local Render Mode Contract

**Files:**
- Modify: `core/job_models.py`
- Modify: `tests/test_api_jobs.py`

- [ ] **Step 1: Write failing API test for `local_render`**

Add this test to `tests/test_api_jobs.py`:

```python
@pytest.mark.asyncio
async def test_start_pipeline_accepts_local_render_mode(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_enqueue(
        queue_name,
        job_data,
        *,
        action,
        max_attempts=3,
        attempt=0,
        job_id=None,
    ):
        captured["queue_name"] = queue_name
        captured["job_data"] = job_data
        captured["action"] = action
        return "job-local-render"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={
                "category": "Science",
                "language": "vi",
                "count": 1,
                "mode": "local_render",
            },
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-local-render"
    assert captured["queue_name"] == "pipeline"
    assert captured["action"] == JobAction.RUN_PIPELINE
    assert captured["job_data"] == {
        "category": "Science",
        "language": "vi",
        "count": 1,
        "mode": PipelineMode.LOCAL_RENDER.value,
    }
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py::test_start_pipeline_accepts_local_render_mode -v
```

Expected: FAIL with enum validation error or `PipelineMode` missing `LOCAL_RENDER`.

- [ ] **Step 3: Implement enum value**

In `core/job_models.py`, update `PipelineMode`:

```python
class PipelineMode(StrEnum):
    PRODUCTION = "production"
    DRY_RUN = "dry_run"
    SMOKE = "smoke"
    LOCAL_RENDER = "local_render"
```

- [ ] **Step 4: Run test and verify pass**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py::test_start_pipeline_accepts_local_render_mode -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/job_models.py tests/test_api_jobs.py
git commit -m "feat: add local render pipeline mode"
```

---

### Task 2: Remotion Data Contract Module

**Files:**
- Create: `core/video_contract.py`
- Test: `tests/test_video_contract_local_render.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_video_contract_local_render.py`:

```python
import pytest

from core.video_contract import (
    VideoContractError,
    build_local_render_video_data,
    validate_video_data,
)


def test_build_local_render_video_data_returns_valid_payload():
    payload = build_local_render_video_data(
        title="Amazing Science Facts",
        category="Science",
        language="vi",
    )

    validate_video_data(payload)

    assert payload["template"] == "timeline"
    assert payload["title"] == "Amazing Science Facts"
    assert payload["language"] == "vi"
    assert payload["musicPath"] == ""
    assert len(payload["cards"]) >= 3
    assert payload["cards"][0]["title"]


def test_validate_video_data_rejects_missing_required_fields():
    payload = {
        "template": "timeline",
        "language": "vi",
        "cards": [],
        "musicPath": "",
        "logoPath": "",
    }

    with pytest.raises(VideoContractError, match="title is required"):
        validate_video_data(payload)


def test_validate_video_data_rejects_empty_cards():
    payload = build_local_render_video_data(
        title="Amazing Science Facts",
        category="Science",
        language="vi",
    )
    payload["cards"] = []

    with pytest.raises(VideoContractError, match="cards must contain at least one card"):
        validate_video_data(payload)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_video_contract_local_render.py -v
```

Expected: FAIL because `core.video_contract` does not exist.

- [ ] **Step 3: Implement contract module**

Create `core/video_contract.py`:

```python
from __future__ import annotations

from typing import Any


class VideoContractError(ValueError):
    """Raised when Remotion video data is missing required fields."""


def build_local_render_video_data(
    *,
    title: str,
    category: str,
    language: str,
) -> dict[str, Any]:
    """Build a minimal Remotion-compatible payload for local render validation."""
    safe_title = title.strip() or f"{category} local render"
    cards = [
        {
            "title": safe_title,
            "subtitle": "Local render validation",
            "description": "This card proves the Python-to-Remotion contract is valid.",
            "imagePath": "",
        },
        {
            "title": f"{category} overview",
            "subtitle": "Fallback section",
            "description": "The local render path can run without upstream AI content.",
            "imagePath": "",
        },
        {
            "title": "Ready for production content",
            "subtitle": language,
            "description": "Replace fallback content with generated research and script data later.",
            "imagePath": "",
        },
    ]

    return {
        "template": "timeline",
        "title": safe_title,
        "category": category,
        "language": language,
        "cards": cards,
        "introCards": [],
        "musicPath": "",
        "logoPath": "",
    }


def validate_video_data(payload: dict[str, Any]) -> None:
    """Validate the minimal fields required by local render Remotion input."""
    if not str(payload.get("template", "")).strip():
        raise VideoContractError("template is required")
    if not str(payload.get("title", "")).strip():
        raise VideoContractError("title is required")
    if not str(payload.get("language", "")).strip():
        raise VideoContractError("language is required")

    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise VideoContractError("cards must contain at least one card")

    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise VideoContractError(f"cards[{index}] must be an object")
        if not str(card.get("title", "")).strip():
            raise VideoContractError(f"cards[{index}].title is required")
        card.setdefault("subtitle", "")
        card.setdefault("description", "")
        card.setdefault("imagePath", "")

    payload.setdefault("musicPath", "")
    payload.setdefault("logoPath", "")
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_video_contract_local_render.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/video_contract.py tests/test_video_contract_local_render.py
git commit -m "feat: add local render video contract"
```

---

### Task 3: Pipeline Local Render Summary

**Files:**
- Modify: `agents/pipeline.py`
- Test: `tests/test_pipeline_local_render.py`

- [ ] **Step 1: Write failing local render pipeline tests**

Create `tests/test_pipeline_local_render.py`:

```python
from pathlib import Path

import pytest

from agents.pipeline import Pipeline


@pytest.mark.asyncio
async def test_run_local_render_returns_stable_summary(monkeypatch, tmp_path):
    async def fake_render(self, *, topic_id, video_data):
        output = tmp_path / "topics" / str(topic_id) / "final_video.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"fake mp4")
        return {
            "video_id": 456,
            "file_path": str(output),
            "duration_sec": 90,
            "status": "rendered",
        }

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    pipeline = Pipeline()

    result = await pipeline.run_local_render(category="Science", language="vi")

    assert result["mode"] == "local_render"
    assert result["category"] == "Science"
    assert result["language"] == "vi"
    assert result["topic_id"] == 1
    assert result["video_id"] == 456
    assert result["duration_sec"] == 90
    assert result["status"] == "rendered"
    assert result["fallback_used"] is True
    assert Path(result["file_path"]).name == "final_video.mp4"


@pytest.mark.asyncio
async def test_run_local_render_validates_video_data_before_render(monkeypatch):
    called = False

    async def fake_render(self, *, topic_id, video_data):
        nonlocal called
        called = True
        return {
            "video_id": 456,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 90,
            "status": "rendered",
        }

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    pipeline = Pipeline()

    result = await pipeline.run_local_render(category="", language="vi")

    assert called is True
    assert result["category"] == "Local"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_pipeline_local_render.py -v
```

Expected: FAIL because `Pipeline.run_local_render` does not exist.

- [ ] **Step 3: Implement local render method**

In `agents/pipeline.py`, add imports:

```python
from pathlib import Path
from core.config import get_settings
from core.video_contract import build_local_render_video_data, validate_video_data
```

Add methods inside `Pipeline` after `run_smoke`:

```python
    async def run_local_render(
        self,
        *,
        category: str,
        language: str = "vi",
    ) -> dict[str, Any]:
        """Create a local render artifact using explicit fallback content."""
        resolved_category = category.strip() or "Local"
        title = f"{resolved_category} Local Render Validation"
        video_data = build_local_render_video_data(
            title=title,
            category=resolved_category,
            language=language,
        )
        validate_video_data(video_data)

        topic_id = 1
        render_result = await self._render_local_video(
            topic_id=topic_id,
            video_data=video_data,
        )

        return {
            "mode": "local_render",
            "category": resolved_category,
            "language": language,
            "topic_id": topic_id,
            "video_id": render_result["video_id"],
            "file_path": render_result["file_path"],
            "duration_sec": render_result["duration_sec"],
            "status": render_result["status"],
            "fallback_used": True,
        }

    async def _render_local_video(
        self,
        *,
        topic_id: int,
        video_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Write a deterministic local render placeholder artifact.

        This helper is intentionally lightweight for v1. It creates a local
        artifact path and stores the validated video data next to it. A later
        iteration can replace this helper with actual Remotion rendering while
        preserving the public `run_local_render` contract.
        """
        settings = get_settings()
        topic_dir = settings.storage_dir / "topics" / str(topic_id)
        topic_dir.mkdir(parents=True, exist_ok=True)

        data_path = topic_dir / "video_data.json"
        data_path.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))

        output_path = topic_dir / "final_video.mp4"
        output_path.write_bytes(b"local render placeholder\n")

        return {
            "video_id": topic_id,
            "file_path": str(output_path.resolve()),
            "duration_sec": 0,
            "status": "rendered",
        }
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_pipeline_local_render.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/pipeline.py tests/test_pipeline_local_render.py
git commit -m "feat: add content pipeline local render"
```

---

### Task 4: Worker Local Render Routing

**Files:**
- Modify: `workers/pipeline_worker.py`
- Test: `tests/test_pipeline_worker.py`

- [ ] **Step 1: Write failing worker test**

Update `tests/test_pipeline_worker.py`.

Extend `StubPipeline`:

```python
        self.local_render_calls: list[tuple[str, str]] = []

    async def run_local_render(self, *, category: str, language: str):
        self.local_render_calls.append((category, language))
        return {
            "mode": "local_render",
            "category": category,
            "language": language,
            "topic_id": 1,
            "video_id": 1,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 0,
            "status": "rendered",
            "fallback_used": True,
        }
```

Add test:

```python
@pytest.mark.asyncio
async def test_worker_routes_local_render_job_to_run_local_render(fake_redis):
    stub = StubPipeline()
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "Science", "language": "vi", "mode": PipelineMode.LOCAL_RENDER.value},
        action=JobAction.RUN_PIPELINE,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: stub)
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    summary = json.loads(metadata["result_summary"])

    assert stub.calls == []
    assert stub.smoke_calls == []
    assert stub.local_render_calls == [("Science", "vi")]
    assert metadata["status"] == JobStatus.COMPLETED.value
    assert summary["mode"] == "local_render"
    assert summary["file_path"] == "/tmp/final_video.mp4"
    assert summary["fallback_used"] is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_pipeline_worker.py::test_worker_routes_local_render_job_to_run_local_render -v
```

Expected: FAIL because worker routes non-production modes to `run_smoke`.

- [ ] **Step 3: Implement worker routing**

In `workers/pipeline_worker.py`, update mode routing:

```python
            elif mode == PipelineMode.LOCAL_RENDER.value:
                result_summary = await pipeline.run_local_render(
                    category=data["category"],
                    language=language,
                )
            else:
                result_summary = await pipeline.run_smoke(
                    category=data["category"],
                    language=language,
                    mode=mode,
                )
```

- [ ] **Step 4: Run worker tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_pipeline_worker.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workers/pipeline_worker.py tests/test_pipeline_worker.py
git commit -m "feat: route local render jobs"
```

---

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Under the existing production control plane examples, add:

```markdown
### Local Render Mode

Use local render mode to produce a local video artifact without uploading to YouTube.

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "local_render"}'
```

Inspect the job result:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

The `result_summary` includes `file_path`, `duration_sec`, `topic_id`, `video_id`, and `fallback_used`.
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
python3 -m pytest tests/test_config_validation.py tests/test_health.py tests/test_queue.py tests/test_api_jobs.py tests/test_pipeline_worker.py tests/test_pipeline_smoke.py tests/test_pipeline_local_render.py tests/test_video_contract.py tests/test_video_contract_local_render.py -v
```

Expected: PASS.

- [ ] **Step 3: Run compile check**

Run:

```bash
python3 -m compileall api core agents workers tests
```

Expected: exit code 0.

- [ ] **Step 4: Validate Docker Compose**

Run:

```bash
docker compose config
```

Expected: exit code 0.

- [ ] **Step 5: Commit docs**

```bash
git add README.md
git commit -m "docs: document content pipeline local render"
```

- [ ] **Step 6: Push**

```bash
git push
```

Expected: `main` pushed to `origin/main`.

---

## Self-Review

- Spec coverage: mode/API is Task 1; video data contract is Task 2; pipeline local render summary is Task 3; worker routing/result summary is Task 4; docs and verification are Task 5.
- Scope: this plan does not upload to YouTube, build analytics learning, add a dashboard, or rewrite Remotion templates.
- Type consistency: the mode name is `local_render` in API payloads, `PipelineMode.LOCAL_RENDER` in Python, and result summaries.
- Test strategy: automated tests mock heavy rendering and validate contracts; manual real Remotion render remains a later hardening step.
