import json

import pytest

from core import queue
from core.job_models import JobAction, JobStatus, PipelineMode
from workers.pipeline_worker import PipelineWorker


class StubPipeline:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []
        self.smoke_calls: list[tuple[str, str, str]] = []

    async def run_full(self, *, category: str, language: str) -> None:
        self.calls.append((category, language))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("temporary failure")

    async def run_smoke(self, *, category: str, language: str, mode: str):
        self.smoke_calls.append((category, language, mode))
        return {
            "mode": mode,
            "category": category,
            "language": language,
            "steps": [],
            "side_effects": {"ai_calls": False, "render": False, "upload": False},
        }


@pytest.mark.asyncio
async def test_worker_marks_success_completed(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "history", "language": "en"},
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline())
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)

    assert metadata["status"] == "completed"
    assert metadata["completed_at"]
    assert metadata["error"] == ""
    assert metadata["result_summary"]
    assert json.loads(metadata["result_summary"])["mode"] == "production"


@pytest.mark.asyncio
async def test_worker_retries_then_fails(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science"},
        max_attempts=1,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline(fail_times=2))
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)

    assert metadata["status"] == "failed"
    assert "temporary failure" in metadata["error"]
    assert metadata["failed_at"]


@pytest.mark.asyncio
async def test_worker_requeues_retry_with_preserved_identity(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science"},
        max_attempts=2,
    )
    original_metadata = await queue.get_job_metadata(job_id)
    envelope = await queue.dequeue("pipeline", timeout=0)

    worker = PipelineWorker(pipeline_factory=lambda: StubPipeline(fail_times=1))
    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)

    assert metadata["status"] == "queued"
    assert metadata["attempt"] == "1"
    assert "temporary failure" in metadata["error"]
    assert await queue.get_queue_length("pipeline") == 1

    retry_envelope = await queue.dequeue("pipeline", timeout=0)

    assert retry_envelope is not None
    assert retry_envelope["job_id"] == job_id
    assert retry_envelope["attempt"] == 1
    assert retry_envelope["created_at"] == original_metadata["created_at"]


@pytest.mark.asyncio
async def test_worker_fails_job_with_missing_category(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"language": "vi"},
        action=JobAction.RUN_PIPELINE,
    )
    envelope = await queue.dequeue("pipeline", timeout=0)
    worker = PipelineWorker(pipeline_factory=lambda: object())

    await worker.process(envelope)

    metadata = await queue.get_job_metadata(job_id)
    assert metadata["status"] == JobStatus.FAILED.value
    assert "category is required" in metadata["error"]


@pytest.mark.asyncio
async def test_worker_does_not_crash_on_malformed_envelope(fake_redis):
    worker = PipelineWorker(pipeline_factory=lambda: object())

    await worker.process(
        {"job_id": "manual-bad-job", "queue": "pipeline", "action": "run_pipeline"}
    )

    metadata = await queue.get_job_metadata("manual-bad-job")
    assert metadata["status"] == JobStatus.FAILED.value
    assert "data must be an object" in metadata["error"]


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
