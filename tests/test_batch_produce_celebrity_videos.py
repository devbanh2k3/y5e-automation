import asyncio
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_produce_batch_returns_success_summary(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    calls = []

    async def fake_produce(*, language, card_layout, write_files):
        calls.append((language, card_layout, write_files))
        index = len(calls)
        return {
            "status": "pending_review",
            "review_id": f"review-{index}",
            "topic_id": f"topic-{index}",
            "video_path": f"/tmp/topic-{index}/final_video.mp4",
            "card_layout": card_layout,
            "youtube_title": f"Video {index}",
            "next_commands": {
                "show_review": f"python3 scripts/review_video.py show review-{index}",
                "approve": f'python3 scripts/review_video.py approve review-{index} --notes "ok"',
            },
        }

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
    )

    assert summary["requested_count"] == 2
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 0
    assert summary["items"][0]["review_id"] == "review-1"
    assert summary["items"][1]["next_commands"]["show_review"].endswith("review-2")
    assert calls == [("en", "flag_hero", True), ("en", "flag_hero", True)]


@pytest.mark.asyncio
async def test_produce_batch_continues_after_failure(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    async def fake_produce(*, language, card_layout, write_files):
        if fake_produce.calls == 1:
            fake_produce.calls += 1
            raise RuntimeError("render failed")
        fake_produce.calls += 1
        return {
            "status": "pending_review",
            "review_id": f"review-{fake_produce.calls}",
            "topic_id": f"topic-{fake_produce.calls}",
            "video_path": f"/tmp/topic-{fake_produce.calls}/final_video.mp4",
            "card_layout": card_layout,
            "youtube_title": "Recovered",
            "next_commands": {},
        }

    fake_produce.calls = 0
    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=3,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
    )

    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["failures"] == [
        {"batch_index": 2, "error": "render failed", "error_type": "RuntimeError"}
    ]
    assert [item["batch_index"] for item in summary["items"]] == [1, 3]


@pytest.mark.asyncio
async def test_produce_batch_stop_on_error(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    async def fake_produce(*, language, card_layout, write_files):
        raise RuntimeError("first render failed")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=3,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=True,
    )

    assert summary["success_count"] == 0
    assert summary["failure_count"] == 1
    assert summary["stopped_on_error"] is True


def test_main_returns_nonzero_when_stop_on_error_fails(monkeypatch, capsys):
    from scripts import batch_produce_celebrity_videos as batch_script

    async def fake_produce_batch(**kwargs):
        return {
            "requested_count": 1,
            "success_count": 0,
            "failure_count": 1,
            "stopped_on_error": True,
            "items": [],
            "failures": [{"batch_index": 1, "error": "failed", "error_type": "RuntimeError"}],
        }

    monkeypatch.setattr(batch_script, "produce_batch", fake_produce_batch)

    exit_code = batch_script.main(["--count", "1", "--stop-on-error"])

    assert exit_code == 1
    assert '"failure_count": 1' in capsys.readouterr().out


def test_cli_help_describes_batch_options():
    result = subprocess.run(
        [sys.executable, "scripts/batch_produce_celebrity_videos.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--count" in result.stdout
    assert "--language" in result.stdout
    assert "--card-layout" in result.stdout
    assert "--stop-on-error" in result.stdout
    assert "--no-write-artifacts" in result.stdout
