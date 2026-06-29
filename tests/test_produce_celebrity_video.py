import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_produce_celebrity_video_script_exists_and_targets_local_render_flow():
    path = ROOT / "scripts" / "produce_celebrity_video.py"
    assert path.exists()
    source = path.read_text()
    assert 'category="Celebrity"' in source
    assert "run_local_render" in source
    assert "pending_review" in source
    assert "review_video.py show" in source
    assert 'card_layout: str = "flag_hero"' in source
    assert "card_layout=card_layout" in source


def test_write_artifacts_persists_review_contracts_next_to_video(tmp_path):
    from scripts.produce_celebrity_video import write_artifacts

    result = {
        "file_path": str(tmp_path / "topics" / "123" / "final_video.mp4"),
        "review_id": "review-1",
        "review_status": "pending_review",
        "content_contract": {"title": "Top Celebrity"},
        "fact_verification_contract": {"schema_version": "fact_verification_contract_v1"},
        "image_verification_contract": {"status": "verified"},
        "quality_gate": {"status": "passed"},
        "stage_timings": {"total": {"seconds": 12.3}},
    }
    review = {
        "review_id": "review-1",
        "content_contract": result["content_contract"],
        "fact_verification_contract": result["fact_verification_contract"],
        "image_verification_contract": result["image_verification_contract"],
        "quality_gate": result["quality_gate"],
    }

    artifacts = write_artifacts(result=result, review=review)

    assert Path(artifacts["review_path"]).exists()
    assert Path(artifacts["content_contract_path"]).exists()
    assert Path(artifacts["fact_verification_contract_path"]).exists()
    assert Path(artifacts["image_verification_contract_path"]).exists()
    assert Path(artifacts["quality_gate_path"]).exists()
    assert Path(artifacts["stage_timings_path"]).exists()
    assert json.loads(Path(artifacts["review_path"]).read_text())["review_id"] == "review-1"
    assert (
        json.loads(Path(artifacts["fact_verification_contract_path"]).read_text())
        == result["fact_verification_contract"]
    )
    assert json.loads(Path(artifacts["quality_gate_path"]).read_text())["status"] == "passed"
    assert json.loads(Path(artifacts["stage_timings_path"]).read_text())["total"]["seconds"] == 12.3


def test_cli_help_describes_review_output_command():
    result = subprocess.run(
        [sys.executable, "scripts/produce_celebrity_video.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--language" in result.stdout
    assert "--card-layout" in result.stdout
    assert "--no-write-artifacts" in result.stdout


@pytest.mark.asyncio
async def test_produce_passes_selected_topic_to_pipeline(monkeypatch):
    from scripts import produce_celebrity_video as producer

    selected_topic = {
        "reservation_id": "reservation-1",
        "title": "Top 10 Most-Awarded Living Musicians",
        "angle": "living_musician_awards",
        "metric_label": "AWARDS",
        "score_total": 91.5,
    }
    captured = {}

    async def fake_run_local_render(
        self,
        *,
        category,
        language,
        card_layout,
        selected_topic,
        duration_target,
    ):
        captured["selected_topic"] = selected_topic
        return {
            "review_status": "pending_review",
            "review_id": "review-1",
            "topic_id": 123,
            "file_path": "/tmp/final_video.mp4",
            "quality_gate": {"status": "passed"},
            "youtube_title": selected_topic["title"],
            "selected_topic": selected_topic,
        }

    async def fake_get_review(review_id):
        return {"review_id": review_id}

    monkeypatch.setattr(producer.Pipeline, "run_local_render", fake_run_local_render)
    monkeypatch.setattr(producer, "get_review", fake_get_review)

    result = await producer.produce(
        language="en",
        card_layout="flag_hero",
        write_files=False,
        selected_topic=selected_topic,
    )

    assert captured["selected_topic"] == selected_topic
    assert result["selected_topic"] == selected_topic


@pytest.mark.asyncio
async def test_produce_passes_duration_target_to_pipeline(monkeypatch):
    from scripts import produce_celebrity_video as producer

    captured = {}

    async def fake_run_local_render(
        self,
        *,
        category,
        language,
        card_layout,
        selected_topic,
        duration_target,
    ):
        captured["duration_target"] = duration_target
        return {
            "review_status": "pending_review",
            "review_id": "review-1",
            "topic_id": 123,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 62,
            "quality_gate": {"status": "passed"},
            "youtube_title": "Title",
            "selected_topic": selected_topic,
        }

    async def fake_get_review(review_id):
        return {"review_id": review_id}

    monkeypatch.setattr(producer.Pipeline, "run_local_render", fake_run_local_render)
    monkeypatch.setattr(producer, "get_review", fake_get_review)

    result = await producer.produce(
        language="en",
        card_layout="flag_hero",
        write_files=False,
        selected_topic={"title": "Topic"},
        duration_profile="standard",
        target_duration=60,
    )

    assert captured["duration_target"] == 60
    assert result["duration_profile"] == "standard"
    assert result["target_duration"] == 60
    assert result["actual_duration_sec"] == 62


@pytest.mark.asyncio
async def test_produce_returns_metadata_for_batch_review_summary(monkeypatch):
    from scripts import produce_celebrity_video as producer

    metadata_variants = {
        "title_variants": [{"title": "Better Title", "score_total": 93}],
        "selected_metadata": {
            "title": "Better Title",
            "description": "Better description.",
            "tags": ["celebrity"],
            "thumbnail_text": "THE GAP",
        },
    }

    async def fake_run_local_render(self, **kwargs):
        return {
            "review_status": "pending_review",
            "review_id": "review-1",
            "topic_id": 123,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 62,
            "quality_gate": {"status": "passed"},
            "youtube_title": "Better Title",
            "metadata_variants": metadata_variants,
            "selected_metadata": metadata_variants["selected_metadata"],
            "selected_topic": kwargs["selected_topic"],
        }

    async def fake_get_review(review_id):
        return {"review_id": review_id}

    monkeypatch.setattr(producer.Pipeline, "run_local_render", fake_run_local_render)
    monkeypatch.setattr(producer, "get_review", fake_get_review)

    result = await producer.produce(
        language="en",
        card_layout="flag_hero",
        write_files=False,
        selected_topic={"title": "Topic"},
    )

    assert result["metadata_variants"] == metadata_variants
    assert result["selected_metadata"]["title"] == "Better Title"
