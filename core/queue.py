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

    await r.lpush(f"queue:{queue_name}", json.dumps(envelope))
    await r.hset(
        f"job:{resolved_job_id}",
        mapping=build_job_metadata(
            job_id=resolved_job_id,
            queue=queue_name,
            action=action,
            attempt=attempt,
            max_attempts=max_attempts,
            created_at=created_at,
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


async def close_queue() -> None:
    """Gracefully close the Redis connection."""
    global _redis  # noqa: PLW0603

    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed.")
