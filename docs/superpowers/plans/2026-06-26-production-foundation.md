# Production Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production backend foundation for the YouTube AI Automation system: structured jobs, dedicated worker processing, visible job status, retry handling, stable pipeline contracts, Docker worker service, and focused tests.

**Architecture:** FastAPI only accepts requests and enqueues jobs. A separate worker process consumes Redis jobs and calls the existing `Pipeline`. Redis stores queue data plus job metadata; PostgreSQL remains the domain system of record. Tests mock Redis, DB, AI, and rendering so the foundation can be verified without real external services.

**Tech Stack:** Python 3.12, FastAPI, Redis async client, PostgreSQL asyncpg, pytest, pytest-asyncio, httpx ASGI transport, Docker Compose.

---

## File Structure

- Modify `requirements.txt`: add test dependencies.
- Create `core/job_models.py`: constants and helpers for job actions/statuses.
- Modify `core/queue.py`: structured job envelope, metadata hash, status helpers, retry helpers.
- Create `workers/__init__.py`: worker package marker.
- Create `workers/pipeline_worker.py`: dedicated async worker entry point and job dispatcher.
- Modify `api/main.py`: enqueue `run_pipeline` jobs and add `GET /api/jobs/{job_id}`.
- Modify `agents/video_agent.py`: include both `id` and `video_id` in video result.
- Modify `docker-compose.yml`: add worker service.
- Create `tests/conftest.py`: shared async fake Redis/test fixtures.
- Create `tests/test_queue.py`: queue envelope and metadata tests.
- Create `tests/test_pipeline_worker.py`: worker success/retry/failure tests.
- Create `tests/test_api_jobs.py`: API enqueue/status tests with mocked queue.
- Create `tests/test_video_contract.py`: `VideoAgent` result contract test via extracted helper or focused monkeypatch.

## Task 1: Add Test Tooling

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add test dependencies**

Append this section to `requirements.txt`:

```txt

# --- Testing ---
pytest>=8.3.0,<9.0
pytest-asyncio>=0.25.0,<1.0
```

- [ ] **Step 2: Verify dependency file parses visually**

Run:

```bash
python -m pip install --dry-run -r requirements.txt
```

Expected: dependency resolution starts successfully. If the environment blocks network access, record that dependency install verification could not be completed and continue with static checks.

## Task 2: Define Job Constants And Metadata Shape

**Files:**
- Create: `core/job_models.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Write failing tests for job constants**

Create `tests/test_queue.py` with:

```python
from core.job_models import JobAction, JobStatus, build_job_metadata


def test_build_job_metadata_has_required_fields():
    metadata = build_job_metadata(
        job_id="job-1",
        queue="pipeline",
        action=JobAction.RUN_PIPELINE,
        attempt=0,
        max_attempts=3,
        created_at="2026-06-26T00:00:00+00:00",
    )

    assert metadata["job_id"] == "job-1"
    assert metadata["queue"] == "pipeline"
    assert metadata["action"] == "run_pipeline"
    assert metadata["status"] == "queued"
    assert metadata["attempt"] == "0"
    assert metadata["max_attempts"] == "3"
    assert metadata["created_at"] == "2026-06-26T00:00:00+00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_queue.py::test_build_job_metadata_has_required_fields -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.job_models'`.

- [ ] **Step 3: Implement job model helpers**

Create `core/job_models.py`:

```python
"""Shared job constants and metadata helpers."""

from __future__ import annotations

from enum import StrEnum


class JobAction(StrEnum):
    """Supported queue actions."""

    RUN_PIPELINE = "run_pipeline"


class JobStatus(StrEnum):
    """Supported job lifecycle statuses."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def build_job_metadata(
    *,
    job_id: str,
    queue: str,
    action: str,
    attempt: int,
    max_attempts: int,
    created_at: str,
    status: str = JobStatus.QUEUED,
    error: str = "",
) -> dict[str, str]:
    """Return Redis-safe string metadata for a job."""
    return {
        "job_id": job_id,
        "queue": queue,
        "action": str(action),
        "status": str(status),
        "attempt": str(attempt),
        "max_attempts": str(max_attempts),
        "created_at": created_at,
        "started_at": "",
        "completed_at": "",
        "failed_at": "",
        "error": error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_queue.py::test_build_job_metadata_has_required_fields -v
```

Expected: PASS.

## Task 3: Refactor Queue To Structured Jobs

**Files:**
- Modify: `core/queue.py`
- Modify: `tests/test_queue.py`

- [ ] **Step 1: Add fake Redis fixture and queue tests**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def ping(self) -> bool:
        return True

    async def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def rpop(self, key: str) -> str | None:
        values = self.lists.get(key, [])
        if not values:
            return None
        return values.pop()

    async def brpop(self, key: str, timeout: int = 0):
        value = await self.rpop(key)
        if value is None:
            return None
        return key, value

    async def hset(self, key: str, mapping=None, *args):
        if mapping is not None:
            self.hashes.setdefault(key, {}).update({str(k): str(v) for k, v in mapping.items()})
            return len(mapping)
        field, value = args
        self.hashes.setdefault(key, {})[str(field)] = str(value)
        return 1

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis(monkeypatch):
    from core import queue

    redis = FakeRedis()
    monkeypatch.setattr(queue, "_redis", redis)
    return redis
```

Append these tests to `tests/test_queue.py`:

```python
import json

import pytest

from core import queue
from core.job_models import JobAction


@pytest.mark.asyncio
async def test_enqueue_creates_structured_envelope_and_metadata(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )

    raw = fake_redis.lists["queue:pipeline"][0]
    envelope = json.loads(raw)
    metadata = await queue.get_job_metadata(job_id)

    assert envelope["job_id"] == job_id
    assert envelope["queue"] == "pipeline"
    assert envelope["action"] == "run_pipeline"
    assert envelope["attempt"] == 0
    assert envelope["max_attempts"] == 3
    assert envelope["data"] == {"category": "science", "language": "vi"}
    assert metadata["status"] == "queued"
    assert metadata["action"] == "run_pipeline"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_queue.py -v
```

Expected: FAIL because `enqueue()` does not accept `action` and `get_job_metadata()` does not exist.

- [ ] **Step 3: Implement structured queue helpers**

Modify `core/queue.py`:

```python
# Add imports
from core.job_models import JobAction, JobStatus, build_job_metadata
```

Replace `enqueue()` with:

```python
async def enqueue(
    queue_name: str,
    job_data: dict[str, Any],
    *,
    action: str = JobAction.RUN_PIPELINE,
    max_attempts: int = 3,
    attempt: int = 0,
    job_id: str | None = None,
) -> str:
    """Push a structured job onto the named queue."""
    r = await get_redis()
    job_id = job_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    envelope: dict[str, Any] = {
        "job_id": job_id,
        "queue": queue_name,
        "action": str(action),
        "data": job_data,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "created_at": created_at,
    }

    await r.lpush(f"queue:{queue_name}", json.dumps(envelope))
    await r.hset(
        f"job:{job_id}",
        mapping=build_job_metadata(
            job_id=job_id,
            queue=queue_name,
            action=str(action),
            attempt=attempt,
            max_attempts=max_attempts,
            created_at=created_at,
        ),
    )

    logger.info("Enqueued job %s on queue '%s'", job_id, queue_name)
    return job_id
```

Add:

```python
async def get_job_metadata(job_id: str) -> dict[str, str]:
    """Return full job metadata, or an empty dict for unknown jobs."""
    r = await get_redis()
    return await r.hgetall(f"job:{job_id}")


async def set_job_metadata(job_id: str, **metadata: Any) -> None:
    """Merge metadata fields into a job hash."""
    r = await get_redis()
    await r.hset(f"job:{job_id}", mapping={k: str(v) for k, v in metadata.items()})
```

Update `get_job_status()`:

```python
async def get_job_status(job_id: str) -> str:
    metadata = await get_job_metadata(job_id)
    return metadata.get("status", "unknown")
```

Update `set_job_status()`:

```python
async def set_job_status(job_id: str, status: str) -> None:
    await set_job_metadata(job_id, status=status)
```

- [ ] **Step 4: Run queue tests**

Run:

```bash
pytest tests/test_queue.py -v
```

Expected: PASS.

## Task 4: Add Worker Dispatch And Retry Logic

**Files:**
- Create: `workers/__init__.py`
- Create: `workers/pipeline_worker.py`
- Create: `tests/test_pipeline_worker.py`

- [ ] **Step 1: Write failing worker tests**

Create `tests/test_pipeline_worker.py`:

```python
import pytest

from core import queue
from core.job_models import JobAction
from workers.pipeline_worker import PipelineWorker


class StubPipeline:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[dict[str, str]] = []

    async def run_full(self, *, category: str, language: str):
        self.calls.append({"category": category, "language": language})
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("temporary failure")
        return {"ok": True}


@pytest.mark.asyncio
async def test_worker_marks_success_completed(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
    )
    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline())

    envelope = await queue.dequeue("pipeline")
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert metadata["status"] == "completed"
    assert metadata["completed_at"]


@pytest.mark.asyncio
async def test_worker_retries_then_fails(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=1,
    )
    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline(fail_times=2))

    envelope = await queue.dequeue("pipeline")
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert metadata["status"] == "failed"
    assert "temporary failure" in metadata["error"]
    assert metadata["failed_at"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_pipeline_worker.py -v
```

Expected: FAIL because `workers.pipeline_worker` does not exist.

- [ ] **Step 3: Implement worker**

Create `workers/__init__.py`:

```python
"""Worker entry points."""
```

Create `workers/pipeline_worker.py`:

```python
"""Dedicated Redis worker for pipeline jobs."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any, Callable

from agents.pipeline import Pipeline
from core import database as db
from core import queue
from core.job_models import JobAction, JobStatus

logger = logging.getLogger("worker.pipeline")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineWorker:
    """Consumes pipeline jobs and dispatches them to the pipeline."""

    def __init__(self, pipeline_factory: Callable[[], Any] | None = None) -> None:
        self.pipeline_factory = pipeline_factory or Pipeline
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def process(self, envelope: dict[str, Any] | None) -> None:
        if envelope is None:
            return

        job_id = envelope["job_id"]
        action = envelope.get("action", "")
        data = envelope.get("data", {})
        attempt = int(envelope.get("attempt", 0))
        max_attempts = int(envelope.get("max_attempts", 3))

        await queue.set_job_metadata(
            job_id,
            status=JobStatus.PROCESSING,
            started_at=utc_now(),
            attempt=attempt,
            error="",
        )

        try:
            if action != JobAction.RUN_PIPELINE:
                raise ValueError(f"Unsupported job action: {action}")

            pipeline = self.pipeline_factory()
            await pipeline.run_full(
                category=data["category"],
                language=data.get("language", "vi"),
            )

        except Exception as exc:
            if attempt + 1 < max_attempts:
                await queue.enqueue(
                    envelope["queue"],
                    data,
                    action=action,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    job_id=job_id,
                )
                await queue.set_job_metadata(
                    job_id,
                    status=JobStatus.QUEUED,
                    attempt=attempt + 1,
                    error=str(exc)[:500],
                )
                return

            await queue.set_job_metadata(
                job_id,
                status=JobStatus.FAILED,
                failed_at=utc_now(),
                error=str(exc)[:500],
            )
            return

        await queue.set_job_metadata(
            job_id,
            status=JobStatus.COMPLETED,
            completed_at=utc_now(),
            error="",
        )

    async def run_forever(self, queue_name: str = "pipeline") -> None:
        while not self._stop.is_set():
            envelope = await queue.dequeue(queue_name, timeout=5)
            await self.process(envelope)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    await db.init_db()
    await queue.init_queue()

    worker = PipelineWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run_forever()
    finally:
        await queue.close_queue()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run worker tests**

Run:

```bash
pytest tests/test_pipeline_worker.py -v
```

Expected: PASS.

## Task 5: Add API Job Status Endpoint

**Files:**
- Modify: `api/main.py`
- Create: `tests/test_api_jobs.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api_jobs.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.mark.asyncio
async def test_start_pipeline_enqueues_run_pipeline(monkeypatch):
    captured = {}

    async def fake_enqueue(queue_name, job_data, *, action, max_attempts=3, attempt=0, job_id=None):
        captured["queue_name"] = queue_name
        captured["job_data"] = job_data
        captured["action"] = action
        return "job-123"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={"category": "science", "language": "vi", "count": 1},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert captured["queue_name"] == "pipeline"
    assert captured["action"] == "run_pipeline"
    assert captured["job_data"] == {"category": "science", "language": "vi", "count": 1}


@pytest.mark.asyncio
async def test_get_job_status_returns_metadata(monkeypatch):
    async def fake_get_job_metadata(job_id):
        return {"job_id": job_id, "status": "queued", "action": "run_pipeline"}

    monkeypatch.setattr("api.main.get_job_metadata", fake_get_job_metadata)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs/job-123")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_get_job_status_unknown_returns_404(monkeypatch):
    async def fake_get_job_metadata(job_id):
        return {}

    monkeypatch.setattr("api.main.get_job_metadata", fake_get_job_metadata)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs/missing")

    assert response.status_code == 404
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
pytest tests/test_api_jobs.py -v
```

Expected: FAIL because `api.main` does not import `get_job_metadata`, start uses `generate_topics`, and `/api/jobs/{job_id}` does not exist.

- [ ] **Step 3: Update API**

Modify imports in `api/main.py`:

```python
from core.job_models import JobAction
from core.queue import (
    init_queue,
    enqueue,
    close_queue,
    get_job_metadata,
    get_queue_length,
)
```

Modify `start_pipeline()` job data:

```python
job_data = {
    "category": body.category,
    "language": body.language,
    "count": body.count,
}
job_id = await enqueue(
    "pipeline",
    job_data,
    action=JobAction.RUN_PIPELINE,
)
```

Add endpoint:

```python
@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str) -> dict[str, Any]:
    """Return metadata for a queued or processed job."""
    metadata = await get_job_metadata(job_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return metadata
```

- [ ] **Step 4: Run API tests**

Run:

```bash
pytest tests/test_api_jobs.py -v
```

Expected: PASS.

## Task 6: Stabilize Video Result Contract

**Files:**
- Modify: `agents/video_agent.py`
- Create: `tests/test_video_contract.py`

- [ ] **Step 1: Write failing test for result shape via a small helper**

Create `tests/test_video_contract.py`:

```python
from agents.video_agent import build_video_result


def test_build_video_result_exposes_id_and_video_id():
    result = build_video_result(
        video_id=42,
        file_path="/tmp/final.mp4",
        duration_sec=123,
        resolution="1920x1080",
    )

    assert result["id"] == 42
    assert result["video_id"] == 42
    assert result["file_path"] == "/tmp/final.mp4"
    assert result["duration_sec"] == 123
    assert result["resolution"] == "1920x1080"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_video_contract.py -v
```

Expected: FAIL because `build_video_result` does not exist.

- [ ] **Step 3: Add helper and use it**

Add near the top-level of `agents/video_agent.py`:

```python
def build_video_result(
    *,
    video_id: int,
    file_path: str,
    duration_sec: int,
    resolution: str,
) -> dict[str, Any]:
    """Return the stable video result contract used by the pipeline."""
    return {
        "id": video_id,
        "video_id": video_id,
        "file_path": file_path,
        "duration_sec": duration_sec,
        "resolution": resolution,
    }
```

Replace the return block in `VideoAgent.run()` with:

```python
return build_video_result(
    video_id=video_id,
    file_path=str(final_output),
    duration_sec=duration_sec,
    resolution=resolution,
)
```

- [ ] **Step 4: Run contract test**

Run:

```bash
pytest tests/test_video_contract.py -v
```

Expected: PASS.

## Task 7: Add Worker To Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add worker service**

Add this service after `api`:

```yaml
  # ── Pipeline worker ────────────────────────────────────────
  worker:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    command: ["python", "-m", "workers.pipeline_worker"]
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://ytbot:ytbot@postgres:5432/youtube_automation
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./output:/app/output
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

- [ ] **Step 2: Validate Compose syntax**

Run:

```bash
docker compose config
```

Expected: Docker Compose prints normalized config without YAML errors. If Docker is unavailable in the environment, record that Compose syntax validation could not be completed.

## Task 8: Run Foundation Test Suite

**Files:**
- All files touched above.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
pytest tests/test_queue.py tests/test_pipeline_worker.py tests/test_api_jobs.py tests/test_video_contract.py -v
```

Expected: PASS.

- [ ] **Step 2: Run import smoke checks**

Run:

```bash
python -m compileall api core agents workers tests
```

Expected: all files compile.

- [ ] **Step 3: Run Docker Compose config validation**

Run:

```bash
docker compose config
```

Expected: valid config.

## Task 9: Update README Operational Notes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add production foundation usage section**

Add a short section after Quick Start:

```markdown
## Production Foundation Services

The API and worker run as separate services.

- `api` accepts requests and enqueues jobs.
- `worker` consumes Redis jobs and runs the pipeline.
- `n8n` should be used for scheduling, webhooks, and notifications, not for core pipeline logic.

Start all services:

```bash
docker compose up -d
```

Start a pipeline job:

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "science", "language": "vi", "count": 1}'
```

Check job status:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```
```

- [ ] **Step 2: Run Markdown grep sanity check**

Run:

```bash
rg -n "Production Foundation Services|/api/jobs" README.md
```

Expected: both strings are found.

## Self-Review Checklist

- [ ] Spec coverage: every acceptance criterion in `docs/superpowers/specs/2026-06-26-production-foundation-design.md` maps to a task above.
- [ ] Placeholder scan: no unfinished placeholders or vague "add tests" instructions remain.
- [ ] Type consistency: `JobAction.RUN_PIPELINE` serializes to `run_pipeline`; job status strings match `queued`, `processing`, `completed`, `failed`.
- [ ] Contract consistency: `VideoAgent.run()` returns both `id` and `video_id`.
- [ ] Execution safety: tests avoid real AI calls, YouTube upload, and Remotion rendering.

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-06-26-production-foundation.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
