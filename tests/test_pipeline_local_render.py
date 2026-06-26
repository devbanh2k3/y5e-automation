from pathlib import Path

import pytest

from agents.pipeline import Pipeline


@pytest.mark.asyncio
async def test_run_local_render_returns_stable_summary(monkeypatch, tmp_path):
    async def fake_render(self, *, topic_id, video_data):
        output = tmp_path / "topics" / str(topic_id) / "final_video.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"fake mp4")
        return {
            "video_id": 456,
            "file_path": str(output),
            "duration_sec": 90,
            "status": "rendered",
        }

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    pipeline = Pipeline()

    result = await pipeline.run_local_render(category="Science", language="vi")

    assert result["mode"] == "local_render"
    assert result["category"] == "Science"
    assert result["language"] == "vi"
    assert result["topic_id"] == 1
    assert result["video_id"] == 456
    assert result["duration_sec"] == 90
    assert result["status"] == "rendered"
    assert result["fallback_used"] is True
    assert Path(result["file_path"]).name == "final_video.mp4"


@pytest.mark.asyncio
async def test_run_local_render_validates_video_data_before_render(monkeypatch):
    called = False

    async def fake_render(self, *, topic_id, video_data):
        nonlocal called
        called = True
        return {
            "video_id": 456,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 90,
            "status": "rendered",
        }

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    pipeline = Pipeline()

    result = await pipeline.run_local_render(category="", language="vi")

    assert called is True
    assert result["category"] == "Local"
