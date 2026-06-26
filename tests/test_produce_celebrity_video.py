import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_produce_celebrity_video_script_exists_and_targets_local_render_flow():
    path = ROOT / "scripts" / "produce_celebrity_video.py"
    assert path.exists()
    source = path.read_text()
    assert 'category="Celebrity"' in source
    assert "run_local_render" in source
    assert "pending_review" in source
    assert "review_video.py show" in source


def test_write_artifacts_persists_review_contracts_next_to_video(tmp_path):
    from scripts.produce_celebrity_video import write_artifacts

    result = {
        "file_path": str(tmp_path / "topics" / "123" / "final_video.mp4"),
        "review_id": "review-1",
        "review_status": "pending_review",
        "content_contract": {"title": "Top Celebrity"},
        "image_verification_contract": {"status": "verified"},
    }
    review = {
        "review_id": "review-1",
        "content_contract": result["content_contract"],
        "image_verification_contract": result["image_verification_contract"],
    }

    artifacts = write_artifacts(result=result, review=review)

    assert Path(artifacts["review_path"]).exists()
    assert Path(artifacts["content_contract_path"]).exists()
    assert Path(artifacts["image_verification_contract_path"]).exists()
    assert json.loads(Path(artifacts["review_path"]).read_text())["review_id"] == "review-1"


def test_cli_help_describes_review_output_command():
    result = subprocess.run(
        [sys.executable, "scripts/produce_celebrity_video.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--language" in result.stdout
    assert "--no-write-artifacts" in result.stdout
