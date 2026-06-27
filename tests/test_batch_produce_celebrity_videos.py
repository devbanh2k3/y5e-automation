import subprocess
import sys
from pathlib import Path

import pytest

from agents.topic_strategy_agent import TopicSelectionError


ROOT = Path(__file__).resolve().parents[1]


def selected_topic(index, *, angle=None, metric=None):
    return {
        "reservation_id": f"reservation-{index}",
        "title": f"Topic {index}",
        "normalized_title": f"topic {index}",
        "category": f"category_{index}",
        "angle": angle or f"angle_{index}",
        "metric_label": metric or f"METRIC {index}",
        "score_total": 90 - index,
        "score_breakdown": {
            "viral": 90,
            "data": 90,
            "novelty": 90,
            "image": 90,
            "safety": 100,
        },
        "selection_reason": "Best diverse candidate",
        "status": "reserved",
    }


class FakeRepository:
    def __init__(self):
        self.produced = []
        self.failed = []

    def mark_produced(self, reservation_id, *, topic_id):
        self.produced.append((reservation_id, topic_id))

    def mark_failed(self, reservation_id, *, reason):
        self.failed.append((reservation_id, reason))


class FakeStrategy:
    def __init__(self, slates):
        self.slates = list(slates)
        self.repository = FakeRepository()
        self.calls = []

    async def run(self, *, count, language, batch_id):
        self.calls.append((count, language, batch_id))
        outcome = self.slates.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def produced_result(index, selected):
    return {
        "status": "pending_review",
        "review_id": f"review-{index}",
        "topic_id": f"topic-{index}",
        "video_path": f"/tmp/topic-{index}/final_video.mp4",
        "card_layout": "flag_hero",
        "youtube_title": selected["title"],
        "quality_gate": {"status": "passed"},
        "next_commands": {
            "show_review": f"python3 scripts/review_video.py show review-{index}",
        },
        "selected_topic": selected,
    }


@pytest.mark.asyncio
async def test_produce_batch_reserves_distinct_slate_and_returns_strategy_summary(
    monkeypatch,
):
    from scripts import batch_produce_celebrity_videos as batch_script

    slate = [
        selected_topic(1, angle="tour_income", metric="TOUR REVENUE"),
        selected_topic(2, angle="music_awards", metric="AWARDS"),
    ]
    strategy = FakeStrategy([slate])
    calls = []

    async def fake_produce(*, language, card_layout, write_files, selected_topic):
        calls.append(selected_topic)
        return produced_result(len(calls), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
    )

    assert summary["requested_count"] == 2
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 0
    assert calls == slate
    assert strategy.repository.produced == [
        ("reservation-1", "topic-1"),
        ("reservation-2", "topic-2"),
    ]
    assert summary["items"][0]["topic_strategy"]["angle"] == "tour_income"
    assert summary["items"][1]["topic_strategy"]["metric_label"] == "AWARDS"
    assert summary["items"][0]["topic_strategy"]["score_total"] == 89


@pytest.mark.asyncio
async def test_produce_batch_marks_failure_and_produces_one_replacement(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    first, failed, replacement = selected_topic(1), selected_topic(2), selected_topic(3)
    strategy = FakeStrategy([[first, failed], [replacement]])
    attempts = []

    async def fake_produce(*, language, card_layout, write_files, selected_topic):
        attempts.append(selected_topic["reservation_id"])
        if selected_topic["reservation_id"] == "reservation-2":
            raise RuntimeError("render failed")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
    )

    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["attempted_count"] == 3
    assert attempts == ["reservation-1", "reservation-2", "reservation-3"]
    assert strategy.repository.failed == [("reservation-2", "render failed")]
    assert len(strategy.calls) == 2


@pytest.mark.asyncio
async def test_produce_batch_reports_exhausted_replacement(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    failed = selected_topic(1)
    strategy = FakeStrategy(
        [[failed], TopicSelectionError("no diverse replacement available")]
    )

    async def fake_produce(*, language, card_layout, write_files, selected_topic):
        raise RuntimeError("content failed")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
    )

    assert summary["success_count"] == 0
    assert summary["failure_count"] == 2
    assert summary["failures"][-1]["error_type"] == "TopicSelectionError"


@pytest.mark.asyncio
async def test_produce_batch_reports_initial_topic_selection_failure(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    strategy = FakeStrategy(
        [TopicSelectionError("could not select 3 diverse Celebrity topics")]
    )

    async def fake_produce(**kwargs):
        raise AssertionError("render must not start without a reserved slate")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=3,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
    )

    assert summary["success_count"] == 0
    assert summary["failure_count"] == 1
    assert summary["attempted_count"] == 0
    assert summary["failures"][0]["error_type"] == "TopicSelectionError"


@pytest.mark.asyncio
async def test_produce_batch_stop_on_error(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    strategy = FakeStrategy([[selected_topic(1), selected_topic(2)]])

    async def fake_produce(*, language, card_layout, write_files, selected_topic):
        raise RuntimeError("first render failed")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=True,
        strategy=strategy,
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
            "failures": [
                {"batch_index": 1, "error": "failed", "error_type": "RuntimeError"}
            ],
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
