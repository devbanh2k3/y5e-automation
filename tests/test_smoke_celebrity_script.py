from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_celebrity.py"
MAKEFILE = ROOT / "Makefile"


def test_smoke_celebrity_script_exists_and_targets_local_render_review_flow() -> None:
    source = SCRIPT.read_text()

    assert '"/api/pipeline/start"' in source
    assert '"/api/ready"' in source
    assert "wait_until_ready" in source
    assert '"category": "Celebrity"' in source
    assert '"mode": "local_render"' in source
    assert '"/api/jobs/{job_id}"' in source
    assert '"/api/reviews/{review_id}"' in source
    assert "pending_review" in source
    assert "video_path" in source
    assert "review_id" in source
    assert "content_contract_path" in source
    assert "image_verification_contract_path" in source


def test_makefile_exposes_smoke_celebrity_target() -> None:
    source = MAKEFILE.read_text()

    assert "smoke-celebrity:" in source
    assert "python3 scripts/smoke_celebrity.py" in source


def test_smoke_celebrity_maps_container_output_path_to_host_path() -> None:
    module = runpy.run_path(str(SCRIPT))

    mapped = module["resolve_host_video_path"]("/app/output/topics/123/final_video.mp4")

    assert mapped == ROOT / "output" / "topics" / "123" / "final_video.mp4"
