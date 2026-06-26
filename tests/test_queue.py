import json

import pytest

from core import queue
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

    assert set(metadata.keys()) == {
        "job_id",
        "queue",
        "action",
        "status",
        "attempt",
        "max_attempts",
        "created_at",
        "started_at",
        "completed_at",
        "failed_at",
        "error",
        "envelope_json",
    }
    assert metadata["job_id"] == "job-1"
    assert metadata["queue"] == "pipeline"
    assert metadata["action"] == "run_pipeline"
    assert metadata["status"] == "queued"
    assert metadata["attempt"] == "0"
    assert metadata["max_attempts"] == "3"
    assert metadata["created_at"] == "2026-06-26T00:00:00+00:00"
    assert metadata["started_at"] == ""
    assert metadata["completed_at"] == ""
    assert metadata["failed_at"] == ""
    assert metadata["error"] == ""
    assert metadata["envelope_json"] == ""


@pytest.mark.asyncio
async def test_enqueue_stores_structured_job_envelope_and_metadata(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"video_id": "vid-123"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )

    assert await fake_redis.llen("queue:pipeline") == 1

    raw_envelope = fake_redis.lists["queue:pipeline"][0]
    envelope = json.loads(raw_envelope)

    assert envelope["job_id"] == job_id
    assert envelope["queue"] == "pipeline"
    assert envelope["action"] == "run_pipeline"
    assert envelope["attempt"] == 0
    assert envelope["max_attempts"] == 3
    assert envelope["data"] == {"video_id": "vid-123"}
    assert envelope["created_at"]

    assert fake_redis.hashes[f"job:{job_id}"]["status"] == "queued"
    assert fake_redis.hashes[f"job:{job_id}"]["action"] == "run_pipeline"
    assert fake_redis.hashes[f"job:{job_id}"]["envelope_json"] == raw_envelope


@pytest.mark.asyncio
async def test_dequeue_timeout_zero_is_non_blocking_and_returns_fifo_jobs(fake_redis):
    first_job_id = await queue.enqueue(
        "pipeline",
        {"category": "first"},
        action=JobAction.RUN_PIPELINE,
    )
    second_job_id = await queue.enqueue(
        "pipeline",
        {"category": "second"},
        action=JobAction.RUN_PIPELINE,
    )

    first_job = await queue.dequeue("pipeline", timeout=0)
    second_job = await queue.dequeue("pipeline", timeout=0)

    assert first_job is not None
    assert second_job is not None
    assert first_job["job_id"] == first_job_id
    assert first_job["data"]["category"] == "first"
    assert second_job["job_id"] == second_job_id
    assert second_job["data"]["category"] == "second"


@pytest.mark.asyncio
async def test_dequeue_marks_job_metadata_as_processing(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "processing-check"},
        action=JobAction.RUN_PIPELINE,
    )

    job = await queue.dequeue("pipeline", timeout=0)

    assert job is not None
    assert job["job_id"] == job_id
    assert await queue.get_job_status(job_id) == "processing"
    assert fake_redis.hashes[f"job:{job_id}"]["status"] == "processing"


@pytest.mark.asyncio
async def test_dequeue_timeout_zero_returns_none_when_queue_is_empty(fake_redis):
    job = await queue.dequeue("pipeline", timeout=0)

    assert job is None


@pytest.mark.asyncio
async def test_requeue_preserves_original_envelope_fields_without_rewriting_metadata(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )
    original_metadata = await queue.get_job_metadata(job_id)
    envelope = await queue.dequeue("pipeline", timeout=0)

    assert envelope is not None

    await queue.requeue(envelope, attempt=1)

    assert await queue.get_queue_length("pipeline") == 1
    retry_raw_envelope = fake_redis.lists["queue:pipeline"][0]
    retry_envelope = json.loads(retry_raw_envelope)
    updated_metadata = await queue.get_job_metadata(job_id)

    assert retry_envelope["job_id"] == job_id
    assert retry_envelope["queue"] == envelope["queue"]
    assert retry_envelope["action"] == envelope["action"]
    assert retry_envelope["data"] == envelope["data"]
    assert retry_envelope["max_attempts"] == envelope["max_attempts"]
    assert retry_envelope["attempt"] == 1
    assert retry_envelope["created_at"] == envelope["created_at"]
    assert updated_metadata == original_metadata | {"status": "processing"}


@pytest.mark.asyncio
async def test_enqueue_indexes_job_for_recent_listing(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
    )

    jobs = await queue.list_jobs(limit=10)

    assert [job["job_id"] for job in jobs] == [job_id]
    assert jobs[0]["queue"] == "pipeline"
    assert jobs[0]["status"] == JobStatus.QUEUED.value


@pytest.mark.asyncio
async def test_list_jobs_filters_by_status_and_queue(fake_redis):
    failed_id = await queue.enqueue(
        "pipeline",
        {"category": "science"},
        action=JobAction.RUN_PIPELINE,
    )
    completed_id = await queue.enqueue(
        "channel_analysis",
        {"channel_url": "https://youtube.com/@x"},
        action=JobAction.CHANNEL_ANALYSIS,
    )
    await queue.set_job_metadata(failed_id, status=JobStatus.FAILED.value)
    await queue.set_job_metadata(completed_id, status=JobStatus.COMPLETED.value)

    jobs = await queue.list_jobs(
        status=JobStatus.FAILED.value,
        queue="pipeline",
        limit=10,
    )

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == failed_id


@pytest.mark.asyncio
async def test_retry_failed_job_requeues_original_envelope(fake_redis):
    job_id = await queue.enqueue(
        "pipeline",
        {"category": "science", "language": "vi"},
        action=JobAction.RUN_PIPELINE,
        max_attempts=3,
    )
    await queue.dequeue("pipeline")
    await queue.set_job_metadata(job_id, status=JobStatus.FAILED.value, error="boom")

    retry_job_id = await queue.retry_failed_job(job_id)

    metadata = await queue.get_job_metadata(retry_job_id)
    assert retry_job_id == job_id
    assert metadata["status"] == JobStatus.QUEUED.value
    assert metadata["attempt"] == "1"
    assert metadata["error"] == ""
    queued_raw = await fake_redis.rpop("queue:pipeline")
    envelope = json.loads(queued_raw)
    assert envelope["job_id"] == job_id
    assert envelope["attempt"] == 1
    assert envelope["data"]["category"] == "science"


@pytest.mark.asyncio
async def test_get_queue_stats_counts_lengths_and_statuses(fake_redis):
    failed_id = await queue.enqueue(
        "pipeline",
        {"category": "science"},
        action=JobAction.RUN_PIPELINE,
    )
    await queue.enqueue(
        "pipeline",
        {"category": "history"},
        action=JobAction.RUN_PIPELINE,
    )
    await queue.set_job_metadata(failed_id, status=JobStatus.FAILED.value)

    stats = await queue.get_queue_stats(["pipeline"])

    assert stats["queues"]["pipeline"]["pending"] == 2
    assert stats["statuses"][JobStatus.FAILED.value] == 1
    assert stats["statuses"][JobStatus.QUEUED.value] == 1
