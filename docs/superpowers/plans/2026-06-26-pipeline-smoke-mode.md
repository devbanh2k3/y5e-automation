# Pipeline Smoke Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe `dry_run` and `smoke` pipeline modes that validate queue, worker, and pipeline wiring without expensive external side effects.

**Architecture:** Execution mode is represented as a typed enum in `core/job_models.py`, accepted by `api/main.py`, stored in Redis job metadata through `core/queue.py`, routed by `workers/pipeline_worker.py`, and implemented by `agents/pipeline.py` as `run_smoke`. Successful workers store a JSON `result_summary` string in job metadata for API inspection.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, Redis asyncio, pytest, pytest-asyncio.

---

## File Map

- Modify `core/job_models.py`: add `PipelineMode` enum and `result_summary` metadata field.
- Modify `core/queue.py`: initialize and reset `result_summary`.
- Modify `api/main.py`: accept and validate `mode`, enqueue it, expose it through job metadata.
- Modify `agents/pipeline.py`: add `run_smoke` with stable no-side-effect summaries.
- Modify `workers/pipeline_worker.py`: route production to `run_full`, smoke/dry_run to `run_smoke`, store `result_summary`.
- Modify `README.md`: document smoke mode startup command and job inspection.
- Modify tests: `tests/test_queue.py`, `tests/test_api_jobs.py`, `tests/test_pipeline_worker.py`.
- Add tests: `tests/test_pipeline_smoke.py`.

---

### Task 1: Mode and Metadata Contracts

**Files:**
- Modify: `core/job_models.py`
- Modify: `core/queue.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Write failing queue metadata tests**

Update `tests/test_queue.py`.

In imports, add `PipelineMode`:

```python
from core.job_models import JobAction, JobStatus, PipelineMode, build_job_metadata
```

In `test_build_job_metadata_has_required_fields`, add `"result_summary"` to the expected key set and assert it defaults to empty string:

```python
assert metadata["result_summary"] == ""
```

In `test_enqueue_stores_structured_job_envelope_and_metadata`, assert new jobs initialize result summary:

```python
assert fake_redis.hashes[f"job:{job_id}"]["result_summary"] == ""
```

Add a new test:

```python
@pytest.mark.asyncio
async def test_retry_failed_job_clears_result_summary(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi", "mode": PipelineMode.SMOKE.value},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )
    await queue.dequeue("pipeline")
    await queue.set_job_metadata(
        job_id,
        status=JobStatus.FAILED.value,
        error="boom",
        result_summary='{"mode":"smoke"}',
    )

    await queue.retry_failed_job(job_id)

    metadata = await queue.get_job_metadata(job_id)
    assert metadata["result_summary"] == ""
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_queue.py -v
```

Expected: FAIL because `PipelineMode` and `result_summary` do not exist.

- [ ] **Step 3: Implement mode enum and result summary metadata**

In `core/job_models.py`, add:

```python
class PipelineMode(StrEnum):
    PRODUCTION = "production"
    DRY_RUN = "dry_run"
    SMOKE = "smoke"
```

Update `build_job_metadata` signature:

```python
    result_summary: str = "",
```

Add to returned mapping:

```python
        "result_summary": result_summary,
```

In `core/queue.py`, update `retry_failed_job` metadata reset:

```python
        result_summary="",
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_queue.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/job_models.py core/queue.py tests/test_queue.py
git commit -m "feat: add pipeline mode metadata contract"
```

---

### Task 2: API Mode Contract

**Files:**
- Modify: `api/main.py`
- Test: `tests/test_api_jobs.py`

- [ ] **Step 1: Write failing API tests**

Update `tests/test_api_jobs.py`.

In imports, add `PipelineMode`:

```python
from core.job_models import JobAction, JobStatus, PipelineMode
```

In `test_start_pipeline_enqueues_run_pipeline`, update request JSON:

```python
json={"category": "science", "language": "vi", "count": 1, "mode": "smoke"},
```

Update expected job data:

```python
assert captured["job_data"] == {
    "category": "science",
    "language": "vi",
    "count": 1,
    "mode": PipelineMode.SMOKE.value,
}
assert "mode smoke" in response.json()["message"]
```

Add tests:

```python
@pytest.mark.asyncio
async def test_start_pipeline_defaults_mode_to_production(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_enqueue(queue_name, job_data, *, action, max_attempts=3, attempt=0, job_id=None):
        captured["job_data"] = job_data
        return "job-123"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={"category": "science", "language": "vi", "count": 1},
        )

    assert response.status_code == 200
    assert captured["job_data"]["mode"] == PipelineMode.PRODUCTION.value


@pytest.mark.asyncio
async def test_start_pipeline_rejects_invalid_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={
                "category": "science",
                "language": "vi",
                "count": 1,
                "mode": "expensive_unknown_mode",
            },
        )

    assert response.status_code == 422
```

In `test_get_job_status_returns_metadata`, add:

```python
"result_summary": '{"mode":"smoke"}',
```

And assert:

```python
assert response.json()["result_summary"] == '{"mode":"smoke"}'
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py -v
```

Expected: FAIL because API request model does not expose `mode`.

- [ ] **Step 3: Implement API mode support**

In `api/main.py`, update import:

```python
from core.job_models import JobAction, JobStatus, PipelineMode
```

Update `PipelineStartRequest`:

```python
    mode: PipelineMode = Field(
        default=PipelineMode.PRODUCTION,
        description="Execution mode: production, dry_run, or smoke",
    )
```

Update `JobMetadataResponse`:

```python
    result_summary: str = ""
```

Update `start_pipeline` job data:

```python
        "mode": body.mode.value,
```

Update response message:

```python
message=(
    f"Pipeline queued for category '{body.category}' "
    f"({body.count} topics, mode {body.mode.value})."
),
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api_jobs.py
git commit -m "feat: accept pipeline execution mode"
```

---

### Task 3: Pipeline Smoke Summary

**Files:**
- Modify: `agents/pipeline.py`
- Test: `tests/test_pipeline_smoke.py`

- [ ] **Step 1: Write failing pipeline smoke tests**

Create `tests/test_pipeline_smoke.py`:

```python
import pytest

from agents.pipeline import Pipeline
from core.job_models import PipelineMode


@pytest.mark.asyncio
async def test_run_smoke_returns_stable_no_side_effect_summary():
    pipeline = Pipeline()

    result = await pipeline.run_smoke(
        category="Science",
        language="vi",
        mode=PipelineMode.SMOKE.value,
    )

    assert result["mode"] == "smoke"
    assert result["category"] == "Science"
    assert result["language"] == "vi"
    assert result["side_effects"] == {
        "ai_calls": False,
        "render": False,
        "upload": False,
    }
    assert [step["name"] for step in result["steps"]] == [
        "topic",
        "research",
        "fact_check",
        "script",
        "assets",
        "render",
        "thumbnail",
        "upload",
    ]
    assert all(step["status"] == "skipped" for step in result["steps"])


@pytest.mark.asyncio
async def test_run_smoke_supports_dry_run_mode():
    pipeline = Pipeline()

    result = await pipeline.run_smoke(
        category="History",
        language="en",
        mode=PipelineMode.DRY_RUN.value,
    )

    assert result["mode"] == "dry_run"
    assert result["category"] == "History"
    assert result["language"] == "en"
    assert result["steps"][0]["reason"] == "dry_run mode"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_pipeline_smoke.py -v
```

Expected: FAIL because `Pipeline.run_smoke` does not exist.

- [ ] **Step 3: Implement `Pipeline.run_smoke`**

In `agents/pipeline.py`, add method inside `Pipeline` after `run_full`:

```python
    async def run_smoke(
        self,
        *,
        category: str,
        language: str = "vi",
        mode: str = "smoke",
    ) -> dict[str, Any]:
        """Return a no-side-effect pipeline summary for deployment validation."""
        reason = f"{mode} mode"
        steps = [
            "topic",
            "research",
            "fact_check",
            "script",
            "assets",
            "render",
            "thumbnail",
            "upload",
        ]
        return {
            "mode": mode,
            "category": category,
            "language": language,
            "steps": [
                {"name": step, "status": "skipped", "reason": reason}
                for step in steps
            ],
            "side_effects": {
                "ai_calls": False,
                "render": False,
                "upload": False,
            },
        }
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_pipeline_smoke.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/pipeline.py tests/test_pipeline_smoke.py
git commit -m "feat: add pipeline smoke summary"
```

---

### Task 4: Worker Mode Routing and Result Summary

**Files:**
- Modify: `workers/pipeline_worker.py`
- Test: `tests/test_pipeline_worker.py`

- [ ] **Step 1: Write failing worker routing tests**

Update `tests/test_pipeline_worker.py`.

Add import:

```python
import json
from core.job_models import JobAction, JobStatus, PipelineMode
```

Update `StubPipeline`:

```python
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []
        self.smoke_calls: list[tuple[str, str, str]] = []

    async def run_smoke(self, *, category: str, language: str, mode: str):
        self.smoke_calls.append((category, language, mode))
        return {
            "mode": mode,
            "category": category,
            "language": language,
            "steps": [],
            "side_effects": {"ai_calls": False, "render": False, "upload": False},
        }
```

Add tests:

```python
@pytest.mark.asyncio
async def test_worker_routes_smoke_job_to_run_smoke(fake_redis):
    stub = StubPipeline()
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi", "mode": PipelineMode.SMOKE.value},
        action=JobAction.RUN_PIPELINE,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: stub)
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert stub.calls == []
    assert stub.smoke_calls == [("science", "vi", "smoke")]
    assert metadata["status"] == JobStatus.COMPLETED.value
    assert json.loads(metadata["result_summary"])["mode"] == "smoke"


@pytest.mark.asyncio
async def test_worker_routes_dry_run_job_to_run_smoke(fake_redis):
    stub = StubPipeline()
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "history", "language": "en", "mode": PipelineMode.DRY_RUN.value},
        action=JobAction.RUN_PIPELINE,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: stub)
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert stub.smoke_calls == [("history", "en", "dry_run")]
    assert json.loads(metadata["result_summary"])["mode"] == "dry_run"


@pytest.mark.asyncio
async def test_worker_fails_unsupported_pipeline_mode(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi", "mode": "unknown"},
        action=JobAction.RUN_PIPELINE,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline())
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert metadata["status"] == JobStatus.FAILED.value
    assert metadata["result_summary"] == ""
    assert "unsupported mode: unknown" in metadata["error"]
```

In `test_worker_marks_success_completed`, assert production remains routed to `run_full`:

```python
assert metadata["result_summary"]
assert json.loads(metadata["result_summary"])["mode"] == "production"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_pipeline_worker.py -v
```

Expected: FAIL because worker ignores mode and does not store result summaries.

- [ ] **Step 3: Implement worker mode routing**

In `workers/pipeline_worker.py`, add import:

```python
import json
```

Update job model import:

```python
from core.job_models import JobAction, JobStatus, PipelineMode
```

After data validation:

```python
        mode = str(data.get("mode", PipelineMode.PRODUCTION.value))
        if mode not in {mode.value for mode in PipelineMode}:
            await self._fail_job(job_id, f"unsupported mode: {mode}")
            return
```

Replace direct `await pipeline.run_full(...)` with:

```python
            if mode == PipelineMode.PRODUCTION.value:
                pipeline_result = await pipeline.run_full(
                    category=data["category"],
                    language=data.get("language", "vi"),
                )
                result_summary = {
                    "mode": mode,
                    "category": data["category"],
                    "language": data.get("language", "vi"),
                    "result": pipeline_result,
                }
            else:
                result_summary = await pipeline.run_smoke(
                    category=data["category"],
                    language=data.get("language", "vi"),
                    mode=mode,
                )
```

When retrying or failing, ensure `result_summary=""` is written.

On success, update metadata:

```python
            result_summary=json.dumps(result_summary, ensure_ascii=False),
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_pipeline_worker.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workers/pipeline_worker.py tests/test_pipeline_worker.py
git commit -m "feat: route worker pipeline modes"
```

---

### Task 5: Docs, Full Verification, Push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, add under Production Control Plane:

```markdown
### Smoke Mode

Use smoke mode before production runs to validate API, Redis, worker, and pipeline wiring without paid AI calls, heavy rendering, or YouTube upload.

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "smoke"}'
```

Then inspect the result summary:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
python3 -m pytest tests/test_config_validation.py tests/test_health.py tests/test_queue.py tests/test_api_jobs.py tests/test_pipeline_worker.py tests/test_pipeline_smoke.py tests/test_video_contract.py -v
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
git commit -m "docs: document pipeline smoke mode"
```

- [ ] **Step 6: Push branch**

```bash
git push
```

Expected: branch `main` pushed to `origin/main`.

---

## Self-Review

- Spec coverage: API mode contract is Task 2; metadata is Task 1; pipeline `run_smoke` is Task 3; worker routing and summary persistence is Task 4; docs and verification are Task 5.
- Scope: this plan does not add dashboard, content intelligence, real upload changes, or workflow engine replacement.
- Type consistency: `PipelineMode`, `result_summary`, and `run_smoke(category=..., language=..., mode=...)` use the same names across tasks.
- Verification: each behavior has a failing test before implementation and a focused passing test command after implementation.
