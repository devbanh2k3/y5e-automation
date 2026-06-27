from pathlib import Path

import pytest

from agents.pipeline import Pipeline
from core.config import get_settings
from core.fact_verification import FactVerificationError
from core.video_contract import build_content_contract_v2


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
    assert result["topic_id"] >= 100000
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
async def test_run_local_render_uses_content_agent_for_celebrity(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    captured: dict[str, object] = {}

    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            captured.setdefault("events", []).append("image")
            captured["image_agent_topic_id"] = topic_id
            captured["image_agent_content_contract"] = content_contract
            captured["image_agent_strict"] = strict
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": len(content_contract["scenes"]),
                "verified_count": len(content_contract["scenes"]),
                "status": "verified",
                "items": [
                    {
                        "scene_index": index,
                        "person_name": scene["title"].split(" ", 1)[1],
                        "expected_title": scene["title"],
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": f"/tmp/real_{index}.webp",
                        "render_image_path": f"images/real_{index}.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
                        "license": "CC BY-SA 4.0",
                        "attribution": "Example photographer",
                        "quality_score": 0.82,
                        "quality_reason": "portrait or stage photo metadata",
                        "identity_confidence": 0.95,
                        "content_match_status": "passed",
                        "needs_human_review": False,
                        "source_adapter": "test",
                        "reject_reason": "",
                    }
                    for index, scene in enumerate(content_contract["scenes"])
                ],
            }

    class FakeContentAgent:
        async def run(
            self,
            *,
            niche,
            language,
                subject,
                card_layout="flag_hero",
                selected_topic=None,
                duration_target=60,
            ):
            captured["content_agent_card_layout"] = card_layout
            captured["selected_topic"] = selected_topic
            return build_content_contract_v2(
                niche="celebrity",
                title="Top 10 người nổi tiếng test",
                hook="Hook test",
                target_audience="Người xem thích thống kê người nổi tiếng.",
                language=language,
                scenes=[
                    {
                        "title": "#10 Celine Dion",
                        "voiceover": "#10 Celine Dion has a public estimate.",
                        "caption": "550M USD",
                        "image_prompt": "real editorial photo of Celine Dion",
                        "statusText": "#10 | 550M USD",
                        "countryCode": "CA",
                        "countryLabel": "CANADA",
                        "metricLabel": "NET WORTH",
                        "metricValue": "550M USD",
                        "factClaim": "Celine Dion has an estimated public net worth of 550M USD.",
                        "factValue": "550M USD",
                        "factUnit": "USD",
                        "factAsOf": "2026",
                        "factContext": "public celebrity net worth estimate",
                    },
                    {
                        "title": "#1 Taylor Swift",
                        "voiceover": "#1 Taylor Swift has a public estimate.",
                        "caption": "1.6B USD",
                        "image_prompt": "real editorial photo of Taylor Swift",
                        "statusText": "#1 | 1.6B USD",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "NET WORTH",
                        "metricValue": "1.6B USD",
                        "factClaim": "Taylor Swift has an estimated public net worth of 1.6B USD.",
                        "factValue": "1.6B USD",
                        "factUnit": "USD",
                        "factAsOf": "2026",
                        "factContext": "public celebrity net worth estimate",
                    },
                ],
                thumbnail_prompt="Celebrity ranking thumbnail",
                youtube_title="Top 10 người nổi tiếng test",
                youtube_description="Public estimates for review.",
                youtube_tags=["celebrity", "data comparison"],
                duration_target=60,
                cardLayout=card_layout,
                contentFormat="ranking",
                metricScope="public celebrity net worth estimates",
                timeScope="through 2026",
            )

    class FakeFactAgent:
        async def run(self, *, content_contract):
            captured.setdefault("events", []).append("fact")
            captured["fact_agent_content_contract"] = content_contract
            return {
                "schema_version": "fact_verification_contract_v1",
                "verification_policy": "ai_only_independent_pass",
                "status": "ai_verified",
                "required_count": 2,
                "verified_count": 1,
                "corrected_count": 1,
                "rejected_count": 0,
                "items": [
                    {
                        "scene_index": 0,
                        "person_name": "Celine Dion",
                        "metric_label": "NET WORTH",
                        "original_value": "550M USD",
                        "verified_value": "560M USD",
                        "unit": "USD",
                        "as_of": "2026",
                        "status": "corrected",
                        "confidence": 0.91,
                        "reason": "Updated public estimate.",
                        "knowledge_cutoff_risk": "medium",
                    },
                    {
                        "scene_index": 1,
                        "person_name": "Taylor Swift",
                        "metric_label": "NET WORTH",
                        "original_value": "1.6B USD",
                        "verified_value": "1.6B USD",
                        "unit": "USD",
                        "as_of": "2026",
                        "status": "verified",
                        "confidence": 0.92,
                        "reason": "Consistent public estimate.",
                        "knowledge_cutoff_risk": "medium",
                    },
                ],
            }

    async def fake_render(self, *, topic_id, video_data):
        captured.setdefault("events", []).append("render")
        captured["video_data"] = video_data
        output = tmp_path / "topics" / str(topic_id) / "final_video.mp4"
        image_dir = output.parent / "images"
        image_dir.mkdir(parents=True)
        output.write_bytes(b"fake mp4")
        for index in range(len(video_data["cards"])):
            (image_dir / f"real_{index}.webp").write_bytes(f"image {index}".encode())
        return {
            "video_id": 456,
            "file_path": str(output),
            "duration_sec": 90,
            "status": "rendered",
        }

    async def fake_create_review(**kwargs):
        captured["review_kwargs"] = kwargs
        return {
            "review_id": "review-123",
            "status": "pending_review",
        }

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    monkeypatch.setattr("agents.pipeline.create_review", fake_create_review)
    monkeypatch.setattr("agents.pipeline.RealImageAgent", FakeRealImageAgent)
    monkeypatch.setattr("agents.pipeline.AIFactVerificationAgent", FakeFactAgent)
    monkeypatch.setattr("agents.content_agent.ContentAgent", FakeContentAgent)

    selected_topic = {
        "reservation_id": "reservation-1",
        "title": "Top 10 Most-Awarded Living Musicians",
        "angle": "living_musician_awards",
        "metric_label": "AWARDS",
        "score_total": 91.5,
    }
    pipeline = Pipeline()
    result = await pipeline.run_local_render(
        category="Celebrity",
        language="vi",
        card_layout="flag_hero",
        selected_topic=selected_topic,
    )

    video_data = captured["video_data"]
    content_contract = video_data["content_contract"]
    review_kwargs = captured["review_kwargs"]
    image_contract = video_data["image_verification_contract"]
    fact_contract = video_data["fact_verification_contract"]

    assert captured["events"] == ["fact", "image", "render"]
    assert result["mode"] == "local_render"
    assert result["category"] == "Celebrity"
    assert result["fallback_used"] is False
    assert result["review_id"] == "review-123"
    assert result["review_status"] == "pending_review"
    assert result["quality_gate"]["status"] == "passed"
    assert result["content_contract"]["niche"] == "celebrity"
    assert result["content_contract"]["cardLayout"] == "flag_hero"
    assert captured["content_agent_card_layout"] == "flag_hero"
    assert captured["selected_topic"] == selected_topic
    assert result["selected_topic"] == selected_topic
    assert result["youtube_title"] == content_contract["youtube_title"]
    assert "người nổi tiếng" in result["youtube_title"].lower()
    assert captured["image_agent_topic_id"] == result["topic_id"]
    assert captured["image_agent_content_contract"] == content_contract
    assert captured["image_agent_strict"] is True
    assert image_contract["status"] == "verified"
    assert review_kwargs["job_id"] == ""
    assert review_kwargs["file_path"].endswith("/final_video.mp4")
    assert review_kwargs["content_contract"] == content_contract
    assert review_kwargs["image_verification_contract"] == image_contract
    assert review_kwargs["fact_verification_contract"] == fact_contract
    assert review_kwargs["quality_gate"]["status"] == "passed"
    assert result["image_verification_contract"] == image_contract
    assert result["fact_verification_contract"] == fact_contract
    assert result["content_contract"]["scenes"][1]["factValue"] == "1.6B USD"
    assert result["content_contract"]["scenes"][0]["factValue"] == "560M USD"
    assert video_data["template"] == "timeline"
    assert video_data["cards"][0]["header"] == "TOP 2"
    assert video_data["cards"][0]["imagePath"] == "images/real_0.webp"
    assert video_data["cards"][0]["statusText"].startswith("#2")
    assert video_data["cards"][0]["metricValue"] == "560M USD"


@pytest.mark.asyncio
async def test_run_local_render_blocks_factual_celebrity_when_fact_gate_rejects(
    monkeypatch,
    tmp_path,
):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    captured: dict[str, object] = {"image_called": False, "render_called": False}

    class FakeContentAgent:
        async def run(self, **kwargs):
            return build_content_contract_v2(
                niche="celebrity",
                title="Celebrity factual test",
                hook="Hook test",
                target_audience="Celebrity data viewers.",
                language="en",
                scenes=[
                    {
                        "title": "#1 Test Person",
                        "voiceover": "Test Person has an uncertain claim.",
                        "caption": "999",
                        "image_prompt": "real editorial photo of Test Person",
                        "statusText": "#1 | 999",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "AWARDS",
                        "metricValue": "999",
                        "factClaim": "Test Person won 999 public awards.",
                        "factValue": "999",
                        "factUnit": "awards",
                        "factAsOf": "2026",
                        "factContext": "public awards count",
                    }
                ],
                thumbnail_prompt="Celebrity factual thumbnail",
                youtube_title="Celebrity factual test",
                youtube_description="Test.",
                youtube_tags=["celebrity"],
                duration_target=60,
                cardLayout="flag_hero",
                contentFormat="ranking",
                metricScope="public awards",
                timeScope="through 2026",
            )

    class FakeFactAgent:
        async def run(self, *, content_contract):
            raise FactVerificationError("all facts must be AI verified")

    class FakeRealImageAgent:
        async def run_for_content_contract(self, **kwargs):
            captured["image_called"] = True
            return {}

    async def fake_render(self, *, topic_id, video_data):
        captured["render_called"] = True
        return {}

    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)
    monkeypatch.setattr("agents.pipeline.RealImageAgent", FakeRealImageAgent)
    monkeypatch.setattr("agents.pipeline.AIFactVerificationAgent", FakeFactAgent)
    monkeypatch.setattr("agents.content_agent.ContentAgent", FakeContentAgent)

    pipeline = Pipeline()
    with pytest.raises(FactVerificationError):
        await pipeline.run_local_render(category="Celebrity", language="en")

    assert captured["image_called"] is False
    assert captured["render_called"] is False


@pytest.mark.asyncio
async def test_run_local_render_passes_duration_target_to_content_agent(
    monkeypatch,
    tmp_path,
):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    captured: dict[str, object] = {}

    class FakeContentAgent:
        async def run(self, **kwargs):
            captured["duration_target"] = kwargs["duration_target"]
            return build_content_contract_v2(
                niche="celebrity",
                title="Duration Test",
                hook="Hook",
                target_audience="Fans",
                language="en",
                scenes=[
                    {
                        "title": "#1 Taylor Swift",
                        "voiceover": "Taylor Swift has a public estimate.",
                        "caption": "1.6B USD",
                        "image_prompt": "real editorial photo of Taylor Swift",
                        "statusText": "#1 | 1.6B USD",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "NET WORTH",
                        "metricValue": "1.6B USD",
                    }
                ],
                thumbnail_prompt="thumbnail",
                youtube_title="Duration Test",
                youtube_description="Description",
                youtube_tags=["celebrity"],
                duration_target=kwargs["duration_target"],
                cardLayout="flag_hero",
            )

    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": 1,
                "verified_count": 1,
                "status": "verified",
                "items": [
                    {
                        "scene_index": 0,
                        "person_name": "Taylor Swift",
                        "expected_title": "#1 Taylor Swift",
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": "/tmp/real_0.webp",
                        "render_image_path": "images/real_0.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
                        "license": "CC BY-SA 4.0",
                        "attribution": "Example photographer",
                        "quality_score": 0.82,
                        "quality_reason": "portrait metadata",
                        "identity_confidence": 0.95,
                        "content_match_status": "passed",
                        "needs_human_review": False,
                        "source_adapter": "test",
                        "reject_reason": "",
                    }
                ],
            }

    async def fake_render(self, *, topic_id, video_data):
        output = tmp_path / "topics" / str(topic_id) / "final_video.mp4"
        image_dir = output.parent / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "real_0.webp").write_bytes(b"image")
        output.write_bytes(b"fake mp4")
        return {"video_id": 1, "file_path": str(output), "duration_sec": 60, "status": "rendered"}

    async def fake_create_review(**kwargs):
        return {"review_id": "review-1", "status": "pending_review"}

    monkeypatch.setattr("agents.content_agent.ContentAgent", FakeContentAgent)
    monkeypatch.setattr("agents.pipeline.RealImageAgent", FakeRealImageAgent)
    monkeypatch.setattr("agents.pipeline.create_review", fake_create_review)
    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)

    result = await Pipeline().run_local_render(
        category="Celebrity",
        language="en",
        card_layout="flag_hero",
        duration_target=75,
    )

    assert captured["duration_target"] == 75
    assert result["content_contract"]["duration_target"] == 75


@pytest.mark.asyncio
async def test_render_local_video_invokes_remotion(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "output"))
    monkeypatch.setenv("REMOTION_BROWSER_EXECUTABLE", "/usr/bin/chromium")

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
        assert "--browser-executable=/usr/bin/chromium" in cmd
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


@pytest.mark.asyncio
async def test_render_local_video_copies_verified_images_to_remotion_public(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "output"))

    storage_image = tmp_path / "output" / "topics" / "7" / "images" / "real_0.webp"
    storage_image.parent.mkdir(parents=True)
    storage_image.write_bytes(b"verified image")

    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            output_path = Path(captured["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake remotion mp4")
            return b"rendered", b""

    async def fake_create_subprocess_exec(*cmd, cwd, stdout, stderr):
        captured["output_path"] = cmd[5]
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    public_image = Path(__file__).resolve().parents[1] / "video_engine" / "public" / "images" / "real_0.webp"
    public_image.unlink(missing_ok=True)

    pipeline = Pipeline()
    try:
        await pipeline._render_local_video(
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
                        "imagePath": "images/real_0.webp",
                        "statusText": "VERIFIED",
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

        assert public_image.read_bytes() == b"verified image"
    finally:
        public_dir = Path(__file__).resolve().parents[1] / "video_engine" / "public"
        (public_dir / "video_data.json").unlink(missing_ok=True)
        (public_dir / "images" / "real_0.webp").unlink(missing_ok=True)
        (public_dir / "images" / "local-logo.svg").unlink(missing_ok=True)
        (public_dir / "images" / "local-placeholder.svg").unlink(missing_ok=True)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_render_local_video_keeps_timeline_composition_for_card_layouts(monkeypatch, tmp_path):
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
        captured["output_path"] = cmd[5]
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    pipeline = Pipeline()
    try:
        await pipeline._render_local_video(
            topic_id=7,
            video_data={
                "template": "timeline",
                "cardLayout": "flag_hero",
                "title": "Local",
                "subtitle": "Science",
                "language": "vi",
                "cards": [
                    {
                        "header": "TOP 1",
                        "title": "Local",
                        "description": "Test",
                        "imagePath": "images/local-placeholder.svg",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "NET WORTH",
                        "metricValue": "550M USD",
                        "statusText": "550M USD",
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

        assert captured["cmd"][4] == "TimelineVideo"
    finally:
        public_dir = Path(__file__).resolve().parents[1] / "video_engine" / "public"
        (public_dir / "video_data.json").unlink(missing_ok=True)
        (public_dir / "images" / "local-logo.svg").unlink(missing_ok=True)
        (public_dir / "images" / "local-placeholder.svg").unlink(missing_ok=True)
        get_settings.cache_clear()
