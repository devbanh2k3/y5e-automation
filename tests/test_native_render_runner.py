from collections import Counter
from pathlib import Path

import pytest

from scripts.native_render_runner import NativeRenderRunner, run_with_heartbeat
from services.render_chunks import RenderChunk
from services.render_encoder import EncoderCapabilities


@pytest.mark.asyncio
async def test_runner_reuses_completed_chunks_after_restart(tmp_path: Path) -> None:
    attempts: Counter[int] = Counter()
    chunks = [RenderChunk(0, 0, 99), RenderChunk(1, 100, 199), RenderChunk(2, 200, 299)]
    completed = tmp_path / "chunk-0000.mp4"
    completed.write_bytes(b"existing chunk")

    async def render_one(chunk: RenderChunk, output: Path) -> None:
        attempts[chunk.index] += 1
        output.write_bytes(f"chunk {chunk.index}".encode())

    runner = NativeRenderRunner(chunk_validator=lambda path, _chunk: path.stat().st_size > 0)
    paths, reused = await runner.render_missing_chunks(
        chunks=chunks,
        chunk_dir=tmp_path,
        render_one=render_one,
        max_parallel=2,
        retries=2,
    )

    assert [path.name for path in paths] == ["chunk-0000.mp4", "chunk-0001.mp4", "chunk-0002.mp4"]
    assert attempts == Counter({1: 1, 2: 1})
    assert reused == 1


@pytest.mark.asyncio
async def test_runner_retries_only_failed_chunk(tmp_path: Path) -> None:
    attempts: Counter[int] = Counter()
    chunks = [RenderChunk(0, 0, 99), RenderChunk(1, 100, 199), RenderChunk(2, 200, 299)]

    async def render_one(chunk: RenderChunk, output: Path) -> None:
        attempts[chunk.index] += 1
        if chunk.index == 1 and attempts[chunk.index] == 1:
            raise RuntimeError("transient chromium failure")
        output.write_bytes(f"chunk {chunk.index}".encode())

    runner = NativeRenderRunner(chunk_validator=lambda path, _chunk: path.stat().st_size > 0)
    await runner.render_missing_chunks(
        chunks=chunks,
        chunk_dir=tmp_path,
        render_one=render_one,
        max_parallel=2,
        retries=2,
    )

    assert attempts == Counter({1: 2, 0: 1, 2: 1})


@pytest.mark.asyncio
async def test_runner_falls_back_when_hardware_encode_fails(tmp_path: Path) -> None:
    attempts: list[str] = []
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(b"joined")

    async def encode(_input: Path, output: Path, profile) -> None:
        attempts.append(profile.name)
        if profile.name == "h264_nvenc":
            raise RuntimeError("NVENC unavailable")
        output.write_bytes(b"encoded")

    runner = NativeRenderRunner(encoder=encode)
    profile = await runner.encode_with_fallback(
        input_path=joined,
        output_path=tmp_path / "final.mp4",
        preference="auto",
        strict=False,
        capabilities=EncoderCapabilities(
            platform="win32",
            working_encoders=frozenset({"h264_nvenc", "libx264"}),
        ),
    )

    assert profile.name == "libx264"
    assert attempts == ["h264_nvenc", "libx264"]


@pytest.mark.asyncio
async def test_runner_snapshots_each_static_card_once(tmp_path: Path) -> None:
    calls = 0
    commands = []
    runner = NativeRenderRunner(project_root=tmp_path)
    (tmp_path / "video_engine" / "public").mkdir(parents=True)
    source = tmp_path / "video_engine" / "src" / "Card.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("version one")
    video_data = {
        "cardLayout": "flag_hero",
        "language": "en",
        "cards": [
            {
                "header": "TOP 1",
                "title": "Person",
                "description": "Fact",
                "imagePath": "images/real_0.webp",
                "statusText": "VALUE: 1",
            }
        ],
    }

    async def fake_run(command, *, cwd, timeout):
        nonlocal calls
        calls += 1
        commands.append(command)
        Path(command[5]).write_bytes(b"snapshot")

    runner._run = fake_run
    first = await runner.prepare_snapshots(
        topic_id="42", video_data=video_data, cache_dir=tmp_path / "cache"
    )
    second = await runner.prepare_snapshots(
        topic_id="42", video_data=video_data, cache_dir=tmp_path / "cache"
    )

    assert calls == 1
    assert "--timeout=120000" in commands[0]
    assert first["cards"][0]["snapshotPath"] == second["cards"][0]["snapshotPath"]

    source.write_text("version two")
    changed = await runner.prepare_snapshots(
        topic_id="42", video_data=video_data, cache_dir=tmp_path / "cache"
    )
    assert calls == 2
    assert changed["cards"][0]["snapshotPath"] != first["cards"][0]["snapshotPath"]


@pytest.mark.asyncio
async def test_long_job_keeps_runner_heartbeat_alive() -> None:
    heartbeats = 0

    async def heartbeat() -> None:
        nonlocal heartbeats
        heartbeats += 1

    async def job() -> str:
        import asyncio

        await asyncio.sleep(0.04)
        return "done"

    result = await run_with_heartbeat(job(), heartbeat=heartbeat, interval_seconds=0.01)

    assert result == "done"
    assert heartbeats >= 2


def test_default_checkpoint_validation_rejects_corrupt_mp4(tmp_path: Path) -> None:
    corrupt = tmp_path / "chunk.mp4"
    corrupt.write_bytes(b"not an mp4" * 500)

    assert NativeRenderRunner._default_chunk_validator(
        corrupt, RenderChunk(0, 0, 299)
    ) is False
