"""Redis-backed async job queue."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from core.config import get_settings
from core.job_models import JobAction, build_job_metadata

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
RECENT_JOBS_KEY = "jobs:recent"
DEFAULT_JOB_LIST_LIMIT = 50


async def init_queue() -> aioredis.Redis:
    """Initialise and cache the async Redis client.

    Returns:
        The connected Redis client.
    """
    global _redis  # noqa: PLW0603

    if _redis is not None:
        return _redis

    settings = get_settings()
    logger.info("Connecting to Redis → %s", settings.redis_url)

    _redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
    )

    # Quick connectivity check
    await _redis.ping()
    logger.info("Redis connection established.")
    return _redis


async def get_redis() -> aioredis.Redis:
    """Return the cached Redis client, initialising if needed."""
    if _redis is None:
        return await init_queue()
    return _redis


async def enqueue(
    queue_name: str,
    job_data: dict[str, Any],
    *,
    action: JobAction = JobAction.RUN_PIPELINE,
    max_attempts: int = 3,
    attempt: int = 0,
    job_id: str | None = None,
) -> str:
    """Push a job onto the named queue.

    Args:
        queue_name: Logical queue name (e.g. ``pipeline``, ``render``).
        job_data: Arbitrary JSON-serialisable payload.

    Returns:
        A unique job ID (UUID4).
    """
    r = await get_redis()
    resolved_job_id = job_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    envelope: dict[str, Any] = {
        "job_id": resolved_job_id,
        "queue": queue_name,
        "action": action.value,
        "data": job_data,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "created_at": created_at,
    }

    serialized_envelope = json.dumps(envelope)

    await r.lpush(f"queue:{queue_name}", serialized_envelope)
    await r.zadd(
        RECENT_JOBS_KEY,
        {resolved_job_id: datetime.fromisoformat(created_at).timestamp()},
    )
    await r.hset(
        f"job:{resolved_job_id}",
        mapping=build_job_metadata(
            job_id=resolved_job_id,
            queue=queue_name,
            action=action,
            attempt=attempt,
            max_attempts=max_attempts,
            created_at=created_at,
            envelope_json=serialized_envelope,
        ),
    )

    logger.info("Enqueued job %s on queue '%s'", resolved_job_id, queue_name)
    return resolved_job_id


async def requeue(envelope: dict[str, Any], *, attempt: int) -> None:
    """Push a retry envelope back onto its original queue.

    Preserves the original envelope identity fields and timestamps while only
    advancing the attempt counter. This helper intentionally does not rewrite
    job metadata.
    """
    r = await get_redis()
    retry_envelope = dict(envelope)
    retry_envelope["attempt"] = attempt
    queue_name = str(retry_envelope["queue"])

    await r.lpush(f"queue:{queue_name}", json.dumps(retry_envelope))
    logger.info(
        "Requeued job %s on queue '%s' for attempt %s",
        retry_envelope.get("job_id", ""),
        queue_name,
        attempt,
    )


async def dequeue(queue_name: str, timeout: int = 0) -> dict[str, Any] | None:
    """Pop the next job from the named queue.

    Args:
        queue_name: Logical queue name.
        timeout: Seconds to block-wait. For this project helper, ``0`` means
            a non-blocking ``RPOP``. Values greater than ``0`` use ``BRPOP``.

    Returns:
        The job envelope dict, or ``None`` if the queue is empty.
    """
    r = await get_redis()
    key = f"queue:{queue_name}"

    if timeout > 0:
        result = await r.brpop(key, timeout=timeout)
        if result is None:
            return None
        raw = result[1]
    else:
        raw = await r.rpop(key)
        if raw is None:
            return None

    envelope: dict[str, Any] = json.loads(raw)
    job_id = envelope.get("job_id", "")

    # Mark as processing
    await set_job_status(job_id, "processing")
    logger.info("Dequeued job %s from queue '%s'", job_id, queue_name)
    return envelope


async def get_job_metadata(job_id: str) -> dict[str, str]:
    """Return all stored metadata fields for a job."""
    r = await get_redis()
    return await r.hgetall(f"job:{job_id}")


async def set_job_metadata(job_id: str, **metadata: str) -> None:
    """Update one or more metadata fields for a job."""
    if not metadata:
        return

    r = await get_redis()
    await r.hset(f"job:{job_id}", mapping=metadata)


async def get_job_status(job_id: str) -> str:
    """Return the current status string for a job.

    Args:
        job_id: The UUID of the job.

    Returns:
        One of ``queued``, ``processing``, ``completed``, ``failed``,
        or ``unknown`` if the job ID is not found.
    """
    metadata = await get_job_metadata(job_id)
    return metadata.get("status", "unknown")


async def set_job_status(job_id: str, status: str) -> None:
    """Update the status of a job.

    Args:
        job_id: The UUID of the job.
        status: New status string.
    """
    await set_job_metadata(job_id, status=status)


async def get_queue_length(queue_name: str) -> int:
    """Return the number of pending jobs in a queue."""
    r = await get_redis()
    return await r.llen(f"queue:{queue_name}")


async def list_jobs(
    *,
    status: str | None = None,
    queue: str | None = None,
    limit: int = DEFAULT_JOB_LIST_LIMIT,
) -> list[dict[str, str]]:
    """Return recent jobs from the Redis job index."""
    r = await get_redis()
    bounded_limit = max(1, limit)
    job_ids = await r.zrevrange(RECENT_JOBS_KEY, 0, max(bounded_limit * 5, bounded_limit) - 1)
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
        if len(jobs) >= bounded_limit:
            break

    return jobs


async def retry_failed_job(job_id: str) -> str:
    """Requeue a failed job using its stored original envelope."""
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
    """Return queue lengths and recent job status counts."""
    statuses: dict[str, int] = {}
    for job in await list_jobs(limit=500):
        job_status = job.get("status", "unknown")
        statuses[job_status] = statuses.get(job_status, 0) + 1

    queues: dict[str, dict[str, int]] = {}
    for queue_name in queue_names:
        queues[queue_name] = {"pending": await get_queue_length(queue_name)}

    return {"queues": queues, "statuses": statuses}


async def close_queue() -> None:
    """Gracefully close the Redis connection."""
    global _redis  # noqa: PLW0603

    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed.")
