# Production Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production control plane for readiness checks, job management, queue metrics, retry, and hardened worker behavior.

**Architecture:** FastAPI remains the control surface. Redis remains the queue and job metadata store, with a sorted index for recent job listing and hashes for job details. New checks live in `core/health.py`, configuration validation stays in `core/config.py`, queue operations stay in `core/queue.py`, and execution transitions stay in `workers/pipeline_worker.py`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Redis asyncio, pytest, pytest-asyncio, Docker Compose.

---

## File Map

- Modify `core/config.py`: add `app_env`, validation result models, and production config validation.
- Create `core/health.py`: dependency check helpers for readiness.
- Modify `core/job_models.py`: add `RETRYING` if missing and shared job response/status constants.
- Modify `core/queue.py`: store retryable envelope JSON, maintain recent job sorted set, list jobs, retry failed jobs, and report queue stats.
- Modify `workers/pipeline_worker.py`: defensive payload validation, clearer state transitions, structured logging fields.
- Modify `api/main.py`: add `/api/ready`, `GET /api/jobs`, `POST /api/jobs/{job_id}/retry`, and `GET /api/queues`.
- Modify `README.md`: document production control plane endpoints and required production env.
- Add/modify tests in `tests/test_config_validation.py`, `tests/test_health.py`, `tests/test_queue.py`, `tests/test_api_jobs.py`, and `tests/test_pipeline_worker.py`.

---

### Task 1: Production Configuration Validation

**Files:**
- Modify: `core/config.py`
- Test: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing tests for config validation**

Create `tests/test_config_validation.py`:

```python
from core.config import Settings


def test_development_allows_placeholder_credentials():
    settings = Settings(app_env="development")

    result = settings.validate_production_config()

    assert result.ok is True
    assert result.errors == {}


def test_production_rejects_placeholder_credentials():
    settings = Settings(
        app_env="production",
        primary_api_key="sk-CHANGE_ME",
        youtube_api_key="",
        database_url="postgresql://ytbot:ytbot@localhost:5432/youtube_automation",
        redis_url="redis://localhost:6379/0",
    )

    result = settings.validate_production_config()

    assert result.ok is False
    assert result.errors["primary_api_key"] == "must be set to a real value"
    assert result.errors["youtube_api_key"] == "must be set to a real value"
    assert "database_url" not in result.errors
    assert "redis_url" not in result.errors


def test_production_accepts_required_real_values():
    settings = Settings(
        app_env="production",
        primary_api_key="sk-real-production-key",
        youtube_api_key="AIza-real-youtube-key",
        database_url="postgresql://user:pass@db:5432/youtube_automation",
        redis_url="redis://redis:6379/0",
    )

    result = settings.validate_production_config()

    assert result.ok is True
    assert result.errors == {}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_config_validation.py -v
```

Expected: FAIL because `Settings.validate_production_config` does not exist.

- [ ] **Step 3: Implement config validation**

In `core/config.py`, add imports and model:

```python
from pydantic import BaseModel
```

Add above `Settings`:

```python
class ConfigValidationResult(BaseModel):
    """Structured production configuration validation result."""

    ok: bool
    errors: dict[str, str]
```

Add field to `Settings`:

```python
app_env: str = "development"
```

Add methods to `Settings`:

```python
    def validate_production_config(self) -> ConfigValidationResult:
        """Validate production-only required configuration without exposing secrets."""
        if self.app_env.lower() != "production":
            return ConfigValidationResult(ok=True, errors={})

        errors: dict[str, str] = {}
        required_values = {
            "primary_api_key": self.primary_api_key,
            "youtube_api_key": self.youtube_api_key,
            "database_url": self.database_url,
            "redis_url": self.redis_url,
        }

        for field_name, value in required_values.items():
            if self._is_missing_or_placeholder(value):
                errors[field_name] = "must be set to a real value"

        return ConfigValidationResult(ok=not errors, errors=errors)

    @staticmethod
    def _is_missing_or_placeholder(value: str) -> bool:
        normalized = value.strip()
        if not normalized:
            return True
        unsafe_markers = ("CHANGE_ME", "your-", "xxx", "placeholder")
        return any(marker.lower() in normalized.lower() for marker in unsafe_markers)
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_config_validation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config_validation.py
git commit -m "feat: validate production configuration"
```

---

### Task 2: Readiness Checks

**Files:**
- Create: `core/health.py`
- Modify: `api/main.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Write failing readiness tests**

Create `tests/test_health.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from core.health import ComponentCheck, ReadinessResult


@pytest.mark.asyncio
async def test_ready_returns_200_when_all_checks_pass(monkeypatch):
    async def fake_readiness():
        return ReadinessResult(
            ok=True,
            checks={
                "database": ComponentCheck(status="ok"),
                "redis": ComponentCheck(status="ok"),
                "storage": ComponentCheck(status="ok"),
                "config": ComponentCheck(status="ok"),
            },
        )

    monkeypatch.setattr("api.main.check_readiness", fake_readiness)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_returns_503_when_any_check_fails(monkeypatch):
    async def fake_readiness():
        return ReadinessResult(
            ok=False,
            checks={
                "database": ComponentCheck(status="error", message="connection failed"),
                "redis": ComponentCheck(status="ok"),
                "storage": ComponentCheck(status="ok"),
                "config": ComponentCheck(status="ok"),
            },
        )

    monkeypatch.setattr("api.main.check_readiness", fake_readiness)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"]["status"] == "error"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_health.py -v
```

Expected: FAIL because `core.health` and `/api/ready` do not exist.

- [ ] **Step 3: Implement health module**

Create `core/health.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.config import get_settings
from core.database import fetchrow
from core.queue import get_redis


class ComponentCheck(BaseModel):
    status: str
    message: str = ""


class ReadinessResult(BaseModel):
    ok: bool
    checks: dict[str, ComponentCheck]


async def check_readiness() -> ReadinessResult:
    settings = get_settings()
    checks: dict[str, ComponentCheck] = {}

    try:
        await fetchrow("SELECT 1 AS ok")
        checks["database"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["database"] = ComponentCheck(status="error", message=str(exc)[:200])

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["redis"] = ComponentCheck(status="error", message=str(exc)[:200])

    try:
        settings.storage_dir
        checks["storage"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["storage"] = ComponentCheck(status="error", message=str(exc)[:200])

    config_result = settings.validate_production_config()
    if config_result.ok:
        checks["config"] = ComponentCheck(status="ok")
    else:
        checks["config"] = ComponentCheck(
            status="error",
            message=", ".join(sorted(config_result.errors.keys())),
        )

    return ReadinessResult(
        ok=all(check.status == "ok" for check in checks.values()),
        checks=checks,
    )
```

- [ ] **Step 4: Add `/api/ready` route**

In `api/main.py`, import:

```python
from fastapi.responses import JSONResponse
from core.health import ReadinessResult, check_readiness
```

Add response model:

```python
class ReadinessResponse(BaseModel):
    status: str
    timestamp: str
    checks: dict[str, Any]
```

Add route after `/api/health`:

```python
@app.get("/api/ready", response_model=ReadinessResponse, tags=["System"])
async def readiness_check() -> JSONResponse | ReadinessResponse:
    result = await check_readiness()
    payload = ReadinessResponse(
        status="ready" if result.ok else "not_ready",
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks={name: check.model_dump() for name, check in result.checks.items()},
    )
    if result.ok:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump())
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/health.py api/main.py tests/test_health.py
git commit -m "feat: add readiness checks"
```

---

### Task 3: Queue Job Index, Listing, Stats, and Retry

**Files:**
- Modify: `core/job_models.py`
- Modify: `core/queue.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Add failing queue tests**

Append to `tests/test_queue.py`:

```python
import json

from core.job_models import JobAction, JobStatus
from core.queue import (
    enqueue,
    get_job_metadata,
    list_jobs,
    retry_failed_job,
    get_queue_stats,
    set_job_metadata,
)


async def test_enqueue_indexes_job_for_recent_listing(fake_redis):
    job_id = await enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
    )

    jobs = await list_jobs(limit=10)

    assert [job["job_id"] for job in jobs] == [job_id]
    assert jobs[0]["queue"] == "pipeline"
    assert jobs[0]["status"] == JobStatus.QUEUED.value


async def test_list_jobs_filters_by_status_and_queue(fake_redis):
    failed_id = await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)
    completed_id = await enqueue("channel_analysis", {"channel_url": "https://youtube.com/@x"}, action=JobAction.CHANNEL_ANALYSIS)
    await set_job_metadata(failed_id, status=JobStatus.FAILED.value)
    await set_job_metadata(completed_id, status=JobStatus.COMPLETED.value)

    jobs = await list_jobs(status=JobStatus.FAILED.value, queue="pipeline", limit=10)

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == failed_id


async def test_retry_failed_job_requeues_original_envelope(fake_redis):
    job_id = await enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )
    await set_job_metadata(job_id, status=JobStatus.FAILED.value, error="boom")

    retry_job_id = await retry_failed_job(job_id)

    metadata = await get_job_metadata(retry_job_id)
    assert retry_job_id == job_id
    assert metadata["status"] == JobStatus.QUEUED.value
    assert metadata["attempt"] == "1"
    assert metadata["error"] == ""
    queued_raw = await fake_redis.rpop("queue:pipeline")
    envelope = json.loads(queued_raw)
    assert envelope["job_id"] == job_id
    assert envelope["attempt"] == 1
    assert envelope["data"]["category"] == "science"


async def test_get_queue_stats_counts_lengths_and_statuses(fake_redis):
    failed_id = await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)
    await enqueue("pipeline", {"category": "history"}, action=JobAction.RUN_PIPELINE)
    await set_job_metadata(failed_id, status=JobStatus.FAILED.value)

    stats = await get_queue_stats(["pipeline"])

    assert stats["queues"]["pipeline"]["pending"] == 2
    assert stats["statuses"][JobStatus.FAILED.value] == 1
    assert stats["statuses"][JobStatus.QUEUED.value] == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_queue.py -v
```

Expected: FAIL because `list_jobs`, `retry_failed_job`, and `get_queue_stats` do not exist.

- [ ] **Step 3: Add retrying status if missing**

In `core/job_models.py`, ensure `JobStatus` includes:

```python
RETRYING = "retrying"
```

- [ ] **Step 4: Implement queue indexes and APIs**

In `core/queue.py`, add constants:

```python
RECENT_JOBS_KEY = "jobs:recent"
DEFAULT_JOB_LIST_LIMIT = 50
```

In `enqueue`, after building `envelope`, compute serialized envelope once and store it:

```python
serialized_envelope = json.dumps(envelope)
await r.lpush(f"queue:{queue_name}", serialized_envelope)
await r.zadd(RECENT_JOBS_KEY, {resolved_job_id: datetime.fromisoformat(created_at).timestamp()})
```

Add `envelope_json=serialized_envelope` to the `hset` mapping.

Add helpers:

```python
async def list_jobs(
    *,
    status: str | None = None,
    queue: str | None = None,
    limit: int = DEFAULT_JOB_LIST_LIMIT,
) -> list[dict[str, str]]:
    r = await get_redis()
    job_ids = await r.zrevrange(RECENT_JOBS_KEY, 0, max(limit * 5, limit) - 1)
    jobs: list[dict[str, str]] = []
    for job_id in job_ids:
        metadata = await get_job_metadata(str(job_id))
        if not metadata:
            continue
        if status and metadata.get("status") != status:
            continue
        if queue and metadata.get("queue") != queue:
            continue
        jobs.append(metadata)
        if len(jobs) >= limit:
            break
    return jobs


async def retry_failed_job(job_id: str) -> str:
    metadata = await get_job_metadata(job_id)
    if not metadata:
        raise KeyError(job_id)
    if metadata.get("status") != "failed":
        raise ValueError("job is not failed")

    envelope_json = metadata.get("envelope_json", "")
    if not envelope_json:
        raise ValueError("job has no retry envelope")

    envelope = json.loads(envelope_json)
    next_attempt = int(metadata.get("attempt", "0")) + 1
    envelope["attempt"] = next_attempt
    queue_name = str(envelope["queue"])
    serialized_envelope = json.dumps(envelope)

    r = await get_redis()
    await r.lpush(f"queue:{queue_name}", serialized_envelope)
    await set_job_metadata(
        job_id,
        status="queued",
        attempt=str(next_attempt),
        error="",
        failed_at="",
        completed_at="",
        envelope_json=serialized_envelope,
    )
    return job_id


async def get_queue_stats(queue_names: list[str]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for job in await list_jobs(limit=500):
        status = job.get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1

    queues: dict[str, dict[str, int]] = {}
    for queue_name in queue_names:
        queues[queue_name] = {"pending": await get_queue_length(queue_name)}

    return {"queues": queues, "statuses": statuses}
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_queue.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/job_models.py core/queue.py tests/test_queue.py
git commit -m "feat: add queue job listing and retry"
```

---

### Task 4: Job Management API Endpoints

**Files:**
- Modify: `api/main.py`
- Test: `tests/test_api_jobs.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_api_jobs.py`:

```python
@pytest.mark.asyncio
async def test_list_jobs_endpoint_returns_recent_jobs(fake_redis):
    job_id = await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"][0]["job_id"] == job_id


@pytest.mark.asyncio
async def test_retry_job_endpoint_returns_409_for_non_failed_job(fake_redis):
    job_id = await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_retry_job_endpoint_requeues_failed_job(fake_redis):
    job_id = await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)
    await set_job_metadata(job_id, status=JobStatus.FAILED.value, error="boom")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 200
    assert response.json()["job_id"] == job_id
    assert response.json()["status"] == JobStatus.QUEUED.value


@pytest.mark.asyncio
async def test_queue_stats_endpoint(fake_redis):
    await enqueue("pipeline", {"category": "science"}, action=JobAction.RUN_PIPELINE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/queues")

    assert response.status_code == 200
    assert response.json()["queues"]["pipeline"]["pending"] == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py -v
```

Expected: FAIL because new endpoints do not exist.

- [ ] **Step 3: Add API response models and imports**

In `api/main.py`, import:

```python
from core.job_models import JobAction, JobStatus
from core.queue import get_queue_stats, list_jobs, retry_failed_job, set_job_metadata
```

Add models:

```python
class JobListResponse(BaseModel):
    jobs: list[JobMetadataResponse]


class JobRetryResponse(BaseModel):
    job_id: str
    status: str
    message: str


class QueueStatsResponse(BaseModel):
    queues: dict[str, dict[str, int]]
    statuses: dict[str, int]
```

- [ ] **Step 4: Implement endpoints**

Add after `get_job`:

```python
@app.get("/api/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_recent_jobs(
    status: str | None = None,
    queue: str | None = None,
    limit: int = 50,
) -> JobListResponse:
    jobs = await list_jobs(status=status, queue=queue, limit=min(max(limit, 1), 100))
    return JobListResponse(jobs=[JobMetadataResponse(**job) for job in jobs])


@app.post("/api/jobs/{job_id}/retry", response_model=JobRetryResponse, tags=["Jobs"])
async def retry_job(job_id: str) -> JobRetryResponse:
    try:
        await retry_failed_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return JobRetryResponse(
        job_id=job_id,
        status=JobStatus.QUEUED.value,
        message="Job requeued.",
    )


@app.get("/api/queues", response_model=QueueStatsResponse, tags=["Jobs"])
async def queue_stats() -> QueueStatsResponse:
    stats = await get_queue_stats(["pipeline", "channel_analysis"])
    return QueueStatsResponse(**stats)
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
python3 -m pytest tests/test_api_jobs.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/main.py tests/test_api_jobs.py
git commit -m "feat: expose job management endpoints"
```

---

### Task 5: Worker Hardening

**Files:**
- Modify: `workers/pipeline_worker.py`
- Test: `tests/test_pipeline_worker.py`

- [ ] **Step 1: Add failing worker tests**

Append to `tests/test_pipeline_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_fails_job_with_missing_category(fake_redis):
    job_id = await enqueue("pipeline", {"language": "vi"}, action=JobAction.RUN_PIPELINE)
    envelope = await dequeue("pipeline")
    worker = PipelineWorker(pipeline_factory=lambda: object())

    await worker.process(envelope)

    metadata = await get_job_metadata(job_id)
    assert metadata["status"] == JobStatus.FAILED.value
    assert "category is required" in metadata["error"]


@pytest.mark.asyncio
async def test_worker_does_not_crash_on_malformed_envelope(fake_redis):
    worker = PipelineWorker(pipeline_factory=lambda: object())

    await worker.process({"job_id": "manual-bad-job", "queue": "pipeline", "action": "run_pipeline"})

    metadata = await get_job_metadata("manual-bad-job")
    assert metadata["status"] == JobStatus.FAILED.value
    assert "data must be an object" in metadata["error"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_pipeline_worker.py -v
```

Expected: FAIL because worker reads `data["category"]` directly and malformed metadata is not consistently written.

- [ ] **Step 3: Implement defensive worker validation**

In `workers/pipeline_worker.py`, add helper methods inside `PipelineWorker`:

```python
    async def _fail_job(self, job_id: str, error: str) -> None:
        await set_job_metadata(
            job_id,
            status=JobStatus.FAILED.value,
            failed_at=utc_now(),
            error=error[:500],
            completed_at="",
        )

    @staticmethod
    def _validate_data(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        if not str(data.get("category", "")).strip():
            raise ValueError("category is required")
        return data
```

At the top of `process`, replace direct field assumptions with:

```python
        job_id = str(envelope.get("job_id", ""))
        if not job_id:
            logger.error("Dropping malformed envelope without job_id: %s", envelope)
            return

        action = str(envelope.get("action", ""))
        queue_name = str(envelope.get("queue", "pipeline"))
        attempt = int(envelope.get("attempt", 0))
        max_attempts = int(envelope.get("max_attempts", 1))
```

Before running the pipeline, validate:

```python
        try:
            data = self._validate_data(envelope.get("data"))
        except ValueError as exc:
            await self._fail_job(job_id, str(exc))
            return
```

When retrying an exception, set status to `JobStatus.RETRYING.value` before requeue or keep queued only after `requeue`; choose one consistent behavior:

```python
                await set_job_metadata(
                    job_id,
                    status=JobStatus.RETRYING.value,
                    attempt=str(next_attempt),
                    error=str(exc)[:500],
                    completed_at="",
                    failed_at="",
                )
                await requeue(envelope, attempt=next_attempt)
                await set_job_metadata(job_id, status=JobStatus.QUEUED.value)
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
git commit -m "fix: harden pipeline worker job handling"
```

---

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, update the production section with:

```markdown
## Production Control Plane

Use `/api/health` for lightweight liveness and `/api/ready` before schedulers start work.

```bash
curl http://localhost:8000/api/ready
```

Job operations:

```bash
curl http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<job_id>
curl -X POST http://localhost:8000/api/jobs/<job_id>/retry
curl http://localhost:8000/api/queues
```

For production, set:

```env
APP_ENV=production
PRIMARY_API_KEY=...
YOUTUBE_API_KEY=...
DATABASE_URL=...
REDIS_URL=...
```
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
python3 -m pytest tests/test_config_validation.py tests/test_health.py tests/test_queue.py tests/test_api_jobs.py tests/test_pipeline_worker.py tests/test_video_contract.py -v
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

- [ ] **Step 5: Commit docs and any final fixes**

```bash
git add README.md
git commit -m "docs: document production control plane"
```

- [ ] **Step 6: Push branch**

```bash
git push
```

Expected: branch `main` pushed to `origin/main`.

---

## Self-Review

- Spec coverage: configuration validation is Task 1; readiness is Task 2; job listing, retry, and queue stats are Tasks 3-4; worker hardening is Task 5; docs and verification are Task 6.
- Scope: this plan does not add dashboard, OAuth automation, new agents, or PostgreSQL job persistence.
- Type consistency: `ConfigValidationResult`, `ComponentCheck`, `ReadinessResult`, `JobMetadataResponse`, `JobListResponse`, `JobRetryResponse`, and `QueueStatsResponse` are defined before use.
- No implementation step depends on a function not created in the same or earlier task.
