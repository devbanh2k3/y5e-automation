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
        "image_verification_contract": {"status": "verified"},
        "quality_gate": {"status": "passed"},
    }
    review = {
        "review_id": "review-1",
        "content_contract": result["content_contract"],
        "image_verification_contract": result["image_verification_contract"],
        "quality_gate": result["quality_gate"],
    }

    artifacts = write_artifacts(result=result, review=review)

    assert Path(artifacts["review_path"]).exists()
    assert Path(artifacts["content_contract_path"]).exists()
    assert Path(artifacts["image_verification_contract_path"]).exists()
    assert Path(artifacts["quality_gate_path"]).exists()
    assert json.loads(Path(artifacts["review_path"]).read_text())["review_id"] == "review-1"
    assert json.loads(Path(artifacts["quality_gate_path"]).read_text())["status"] == "passed"


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
