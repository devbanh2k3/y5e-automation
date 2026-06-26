import json
import subprocess
import sys

import pytest

from core.config import get_settings
from core.reviews import create_review


@pytest.fixture
def review_cli_env(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


async def create_cli_review():
    return await create_review(
        job_id="job-1",
        topic_id=11,
        video_id=22,
        file_path="/tmp/final.mp4",
        content_contract={"title": "Video"},
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail",
    )


@pytest.mark.asyncio
async def test_review_cli_list_outputs_pending_summary(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [sys.executable, "scripts/review_video.py", "list", "--status", "pending_review"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["reviews"][0]["review_id"] == review["review_id"]
    assert payload["reviews"][0]["title"] == "Title"
    assert payload["reviews"][0]["video_path"] == "/tmp/final.mp4"


@pytest.mark.asyncio
async def test_review_cli_show_outputs_full_review(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [sys.executable, "scripts/review_video.py", "show", review["review_id"]],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["review_id"] == review["review_id"]
    assert payload["content_contract"]["title"] == "Video"


@pytest.mark.asyncio
async def test_review_cli_approve_updates_status(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/review_video.py",
            "approve",
            review["review_id"],
            "--notes",
            "looks good",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "approved"
    assert payload["review_notes"] == "looks good"


@pytest.mark.asyncio
async def test_review_cli_reject_stores_reason_and_scene(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/review_video.py",
            "reject",
            review["review_id"],
            "--reason",
            "wrong_image",
            "--scene",
            "5",
            "--notes",
            "wrong person",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "rejected"
    assert payload["reject_reason"] == "wrong_image"
    assert payload["rejected_scenes"] == [5]
