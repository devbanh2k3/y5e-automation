"""Redis protocol for host-native rendering."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from core.config import get_settings
from core.queue import get_redis
from core.render_contract import NativeRenderRequest, NativeRenderResult

RUNNERS_KEY = "render:runners"


def _job_key(job_id: str) -> str:
    return f"render:job:{job_id}"


def _result_key(job_id: str) -> str:
    return f"render:result:{job_id}"


def _runner_key(runner_id: str) -> str:
    return f"render:runner:{runner_id}"


async def enqueue_render(request: NativeRenderRequest) -> str:
    """Enqueue one render request, deduplicated by its contract identity."""
    redis = await get_redis()
    job_id = str(uuid.uuid4())
    identity_key = f"render:idempotency:{request.idempotency_key}"
    created = await redis.set(identity_key, job_id, nx=True)
    if not created:
        existing = await redis.get(identity_key)
        if existing:
            return str(existing)
        raise RuntimeError("render idempotency record changed concurrently")

    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        _job_key(job_id),
        mapping={
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "request_json": request.model_dump_json(),
        },
    )
    queue_name = get_settings().native_render_queue
    await redis.lpush(
        f"queue:{queue_name}",
        json.dumps({"job_id": job_id, "request": request.model_dump(mode="json")}),
    )
    return job_id


async def claim_render(*, timeout_seconds: int = 5) -> tuple[str, NativeRenderRequest] | None:
    """Claim the oldest native render job."""
    redis = await get_redis()
    queue_name = get_settings().native_render_queue
    result = await redis.brpop(f"queue:{queue_name}", timeout=timeout_seconds)
    if result is None:
        return None
    payload = json.loads(result[1])
    job_id = str(payload["job_id"])
    await set_render_status(job_id, "processing")
    return job_id, NativeRenderRequest.model_validate(payload["request"])


async def set_render_status(job_id: str, status: str, **metadata: str) -> None:
    """Update job state and diagnostic metadata."""
    redis = await get_redis()
    mapping = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **{key: str(value) for key, value in metadata.items()},
    }
    await redis.hset(_job_key(job_id), mapping=mapping)


async def complete_render(
    job_id: str,
    *,
    status: str,
    output_path: str = "",
    encoder: str = "",
    error_code: str = "",
    message: str = "",
    metrics: dict[str, Any] | None = None,
) -> NativeRenderResult:
    """Publish a terminal render result."""
    redis = await get_redis()
    result = NativeRenderResult(
        job_id=job_id,
        status=status,
        output_path=output_path,
        encoder=encoder,
        error_code=error_code,
        message=message,
        metrics=metrics or {},
    )
    await redis.set(_result_key(job_id), result.model_dump_json(), ex=7 * 24 * 60 * 60)
    await set_render_status(job_id, status, error_code=error_code, message=message)
    return result


async def wait_for_render_result(
    job_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = 1.0,
) -> NativeRenderResult:
    """Wait for a terminal result without blocking the event loop."""
    redis = await get_redis()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        raw = await redis.get(_result_key(job_id))
        if raw:
            return NativeRenderResult.model_validate_json(raw)
        await asyncio.sleep(max(0, poll_seconds))
    raise TimeoutError(f"native render result timed out after {timeout_seconds:g}s")


async def publish_runner_heartbeat(
    *,
    runner_id: str,
    capabilities: dict[str, Any],
    ttl_seconds: int,
) -> None:
    """Advertise a runner with an expiring capability record."""
    redis = await get_redis()
    payload = json.dumps(
        {
            "runner_id": runner_id,
            "capabilities": capabilities,
            "reported_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await redis.set(_runner_key(runner_id), payload, ex=max(1, ttl_seconds))
    await redis.sadd(RUNNERS_KEY, runner_id)


async def has_live_runner() -> bool:
    """Return whether any registered runner still has a heartbeat."""
    redis = await get_redis()
    runner_ids = await redis.smembers(RUNNERS_KEY)
    for runner_id in runner_ids:
        if await redis.get(_runner_key(str(runner_id))):
            return True
    return False
