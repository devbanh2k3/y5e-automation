from pathlib import Path

import pytest

from core.render_contract import NativeRenderRequest
from core.render_queue import (
    complete_render,
    enqueue_render,
    has_live_runner,
    publish_runner_heartbeat,
    wait_for_render_result,
)


@pytest.fixture
def render_request(tmp_path: Path) -> NativeRenderRequest:
    root = tmp_path / "output"
    return NativeRenderRequest.create(
        task_id="task-1",
        topic_id="42",
        output_root=root,
        video_data_path=root / "topics" / "42" / "video_data.json",
        output_path=root / "topics" / "42" / "final_video.mp4",
        composition_id="ComparisonVideo",
        target_duration=300,
    )


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_by_render_key(fake_redis, render_request) -> None:
    first = await enqueue_render(render_request)
    second = await enqueue_render(render_request)

    assert first == second
    assert await fake_redis.llen("queue:native_render") == 1


@pytest.mark.asyncio
async def test_runner_heartbeat_expires(fake_redis) -> None:
    await publish_runner_heartbeat(
        runner_id="mac-studio",
        capabilities={"encoders": ["h264_videotoolbox"]},
        ttl_seconds=1,
    )
    assert await has_live_runner() is True

    await fake_redis.delete("render:runner:mac-studio")

    assert await has_live_runner() is False


@pytest.mark.asyncio
async def test_wait_for_result_returns_structured_failure(
    fake_redis, render_request
) -> None:
    job_id = await enqueue_render(render_request)
    await complete_render(
        job_id,
        status="failed",
        error_code="chunk_failed",
        message="chunk 2",
    )

    result = await wait_for_render_result(job_id, timeout_seconds=1, poll_seconds=0)

    assert result.status == "failed"
    assert result.error_code == "chunk_failed"
    assert result.message == "chunk 2"
