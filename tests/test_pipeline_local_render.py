from pathlib import Path

import pytest

from agents.pipeline import Pipeline
from core.config import get_settings


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


@pytest.mark.asyncio
async def test_render_local_video_invokes_remotion(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "output"))

    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            output_path = Path(captured["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake remotion mp4")
            return b"rendered", b""

    async def fake_create_subprocess_exec(*cmd, cwd, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["output_path"] = cmd[5]
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    pipeline = Pipeline()
    try:
        result = await pipeline._render_local_video(
            topic_id=7,
            video_data={
                "template": "timeline",
                "title": "Local",
                "subtitle": "Science",
                "language": "vi",
                "cards": [
                    {
                        "header": "LOCAL 1",
                        "title": "Local",
                        "description": "Test",
                        "imagePath": "images/local-placeholder.svg",
                        "statusText": "FALLBACK",
                    }
                ],
                "introCards": [],
                "musicPath": "",
                "sfxPaths": {"transition": "", "alert": "", "reveal": ""},
                "logoPath": "images/local-logo.svg",
                "holdDurationFrames": 120,
                "transitionDurationFrames": 15,
            },
        )

        cmd = captured["cmd"]
        assert cmd[:5] == ("npx", "remotion", "render", "src/index.tsx", "TimelineVideo")
        assert "--codec=h264" in cmd
        assert Path(result["file_path"]).read_bytes() == b"fake remotion mp4"
        assert result["duration_sec"] == 0
        assert result["status"] == "rendered"
    finally:
        public_dir = Path(__file__).resolve().parents[1] / "video_engine" / "public"
        (public_dir / "video_data.json").unlink(missing_ok=True)
        (public_dir / "images" / "local-logo.svg").unlink(missing_ok=True)
        (public_dir / "images" / "local-placeholder.svg").unlink(missing_ok=True)
        get_settings.cache_clear()
