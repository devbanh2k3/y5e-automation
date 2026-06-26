import pytest

from core import queue
from workers.pipeline_worker import PipelineWorker


class StubPipeline:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []

    async def run_full(self, *, category: str, language: str) -> None:
        self.calls.append((category, language))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("temporary failure")


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
