import json
import subprocess
import sys
from pathlib import Path

import pytest

from agents.topic_strategy_agent import TopicSelectionError
from core.config import get_settings
from core.fact_verification import FactVerificationError
from core.video_contract import VideoContractError


ROOT = Path(__file__).resolve().parents[1]


def test_resolve_duration_target_uses_profile_defaults():
    from scripts.batch_produce_celebrity_videos import resolve_duration_target

    assert resolve_duration_target("short", None) == 40
    assert resolve_duration_target("standard", None) == 60
    assert resolve_duration_target("long", None) == 90


def test_resolve_duration_target_allows_explicit_override():
    from scripts.batch_produce_celebrity_videos import resolve_duration_target

    assert resolve_duration_target("standard", 75) == 75


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (VideoContractError("scenes[0].factClaim is required"), "repairable_contract"),
        (VideoContractError("scenes[8].countryCode is not supported"), "repairable_contract"),
        (
            FactVerificationError("all facts must be AI verified with confidence >= 0.80"),
            "fact_rejected",
        ),
        (RuntimeError("image verification failed: wrong person"), "image_failed"),
        (RuntimeError("remotion render failed with exit code 1"), "render_failed"),
        (ValueError("Could not extract valid JSON from response: {"), "ai_output_invalid"),
        (
            ValueError("AI celebrity contract requires at least 24 scenes, got 10"),
            "ai_output_invalid",
        ),
        (TopicSelectionError("could not select diverse topics"), "topic_selection_failed"),
        (RuntimeError("anything else"), "unknown"),
    ],
)
def test_classify_batch_failure(exc, expected):
    from scripts.batch_produce_celebrity_videos import classify_batch_failure

    assert classify_batch_failure(exc) == expected


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
        "duration_profile": "standard",
        "target_duration": 60,
        "actual_duration_sec": 61,
        "youtube_title": selected["title"],
        "quality_gate": {"status": "passed"},
        "metadata_variants": {
            "title_variants": [
                {"title": selected["title"], "score_total": 86.5},
            ],
            "selected_metadata": {
                "title": selected["title"],
                "description": "Optimized description.",
                "tags": ["celebrity"],
                "thumbnail_text": "THE GAP",
            },
        },
        "selected_metadata": {
            "title": selected["title"],
            "description": "Optimized description.",
            "tags": ["celebrity"],
            "thumbnail_text": "THE GAP",
        },
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

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
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
    assert summary["items"][0]["metadata_score"] == 86.5
    assert summary["items"][0]["quality_status"] == "passed"


@pytest.mark.asyncio
async def test_produce_batch_v2_fills_requested_count_with_replacements(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    failed = selected_topic(1)
    second = selected_topic(2)
    replacement = selected_topic(3)
    strategy = FakeStrategy([[failed, second], [replacement]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
        attempts.append(selected_topic["reservation_id"])
        if selected_topic["reservation_id"] == "reservation-1":
            raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=4,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["success_count"] == 2
    assert summary["requested_count"] == 2
    assert summary["replacement_count"] == 1
    assert summary["unfilled_count"] == 0
    assert summary["status"] == "completed_with_recoveries"
    assert attempts == ["reservation-1", "reservation-2", "reservation-3"]
    assert summary["failures"][0]["classification"] == "fact_rejected"
    assert summary["failures"][0]["recovery_action"] == "request_replacement"


@pytest.mark.asyncio
async def test_produce_batch_v2_retries_repairable_contract_once(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    topic = selected_topic(1)
    strategy = FakeStrategy([[topic]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
        attempts.append(selected_topic["reservation_id"])
        if len(attempts) == 1:
            raise VideoContractError("scenes[0].factClaim is required")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["success_count"] == 1
    assert summary["retry_count"] == 1
    assert summary["replacement_count"] == 0
    assert attempts == ["reservation-1", "reservation-1"]
    assert summary["failures"][0]["classification"] == "repairable_contract"
    assert summary["failures"][0]["recovery_action"] == "retry_same_topic"


@pytest.mark.asyncio
async def test_produce_batch_replaces_invalid_ai_output(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    failed = selected_topic(1)
    replacement = selected_topic(2)
    strategy = FakeStrategy([[failed], [replacement]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
        attempts.append(selected_topic["reservation_id"])
        if selected_topic["reservation_id"] == "reservation-1":
            raise ValueError("AI celebrity contract requires at least 24 scenes, got 10")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
    )

    assert summary["success_count"] == 1
    assert summary["replacement_count"] == 1
    assert attempts == ["reservation-1", "reservation-2"]
    assert summary["failures"][0]["classification"] == "ai_output_invalid"
    assert summary["failures"][0]["recovery_action"] == "request_replacement"


@pytest.mark.asyncio
async def test_produce_batch_retries_initial_topic_reservation_race(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    topic = selected_topic(1)
    strategy = FakeStrategy(
        [TopicSelectionError("topic reservations changed concurrently"), [topic]]
    )

    async def fake_produce(**kwargs):
        return produced_result(1, kwargs["selected_topic"])

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
    )

    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["failures"][0]["classification"] == "topic_selection_race"
    assert summary["failures"][0]["recovery_action"] == "retry_topic_selection"
    assert len(strategy.calls) == 2


@pytest.mark.asyncio
async def test_produce_batch_v2_stops_at_max_attempts(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    topics = [selected_topic(index) for index in range(1, 6)]
    strategy = FakeStrategy([[topics[0]], [topics[1]], [topics[2]], [topics[3]]])

    async def fake_produce(**kwargs):
        raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["attempted_count"] == 3
    assert summary["success_count"] == 0
    assert summary["unfilled_count"] == 2
    assert summary["status"] == "incomplete"
    assert summary["failures"][-1]["recovery_action"] == "attempt_budget_exhausted"


@pytest.mark.asyncio
async def test_produce_batch_marks_failure_and_produces_one_replacement(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    first, failed, replacement = selected_topic(1), selected_topic(2), selected_topic(3)
    strategy = FakeStrategy([[first, failed], [replacement]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
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
    assert summary["failure_count"] == 2
    assert summary["attempted_count"] == 4
    assert summary["retry_count"] == 1
    assert attempts == ["reservation-1", "reservation-2", "reservation-2", "reservation-3"]
    assert strategy.repository.failed == [
        ("reservation-2", "render failed"),
        ("reservation-2", "render failed"),
    ]
    assert len(strategy.calls) == 2


@pytest.mark.asyncio
async def test_produce_batch_reports_exhausted_replacement(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    failed = selected_topic(1)
    strategy = FakeStrategy(
        [[failed], TopicSelectionError("no diverse replacement available")]
    )

    async def fake_produce(**kwargs):
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

    async def fake_produce(**kwargs):
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


def test_cli_accepts_batch_v2_options():
    from scripts.batch_produce_celebrity_videos import build_parser

    args = build_parser().parse_args(
        [
            "--count",
            "10",
            "--language",
            "en",
            "--card-layout",
            "flag_hero",
            "--max-attempts",
            "30",
            "--duration-profile",
            "long",
            "--target-duration",
            "95",
        ]
    )

    assert args.max_attempts == 30
    assert args.duration_profile == "long"
    assert args.target_duration == 95


def test_main_passes_batch_v2_options(monkeypatch, capsys):
    from scripts import batch_produce_celebrity_videos as batch_script

    captured = {}

    async def fake_produce_batch(**kwargs):
        captured.update(kwargs)
        return {
            "requested_count": 2,
            "success_count": 2,
            "failure_count": 0,
            "stopped_on_error": False,
            "items": [],
            "failures": [],
        }

    monkeypatch.setattr(batch_script, "produce_batch", fake_produce_batch)

    exit_code = batch_script.main(
        [
            "--count",
            "2",
            "--max-attempts",
            "5",
            "--duration-profile",
            "short",
            "--target-duration",
            "45",
        ]
    )

    assert exit_code == 0
    assert captured["max_attempts"] == 5
    assert captured["duration_profile"] == "short"
    assert captured["target_duration"] == 45
    assert '"success_count": 2' in capsys.readouterr().out


def test_format_batch_report_prioritizes_review_items_and_checklist():
    from scripts.batch_produce_celebrity_videos import format_batch_report

    summary = {
        "status": "completed_with_recoveries",
        "batch_id": "batch-1",
        "requested_count": 2,
        "success_count": 2,
        "failure_count": 1,
        "manifest_path": "/tmp/output/batches/batch-1.json",
        "items": [
            {
                "review_id": "review-low",
                "quality_status": "passed",
                "metadata_score": 72,
                "youtube_title": "Low Score Title",
                "video_path": "/tmp/low.mp4",
                "actual_duration_sec": 58,
                "topic_strategy": {"score_total": 82, "metric_label": "FOLLOWERS"},
            },
            {
                "review_id": "review-high",
                "quality_status": "passed",
                "metadata_score": 94,
                "youtube_title": "High Score Title",
                "video_path": "/tmp/high.mp4",
                "actual_duration_sec": 61,
                "topic_strategy": {"score_total": 91, "metric_label": "AWARDS"},
            },
        ],
        "failures": [
            {
                "batch_slot": 1,
                "classification": "fact_rejected",
                "recovery_action": "request_replacement",
                "error": "all facts must be verified",
            }
        ],
    }

    report = format_batch_report(summary)

    assert "PRODUCTION BATCH REPORT" in report
    assert "batch-1" in report
    assert "Review Priority" in report
    assert report.index("review-high") < report.index("review-low")
    assert "metadata=94" in report
    assert "Quality passed: 2/2" in report
    assert "Failures" in report
    assert "fact_rejected" in report
    assert "Production Checklist" in report
    assert "Open Review UI" in report
    assert "http://127.0.0.1:8000/review-ui" in report


def test_main_prints_human_report_when_requested(monkeypatch, capsys):
    from scripts import batch_produce_celebrity_videos as batch_script

    async def fake_produce_batch(**kwargs):
        return {
            "status": "completed",
            "batch_id": "batch-1",
            "requested_count": 1,
            "success_count": 1,
            "failure_count": 0,
            "stopped_on_error": False,
            "manifest_path": "/tmp/output/batches/batch-1.json",
            "items": [
                {
                    "review_id": "review-1",
                    "quality_status": "passed",
                    "metadata_score": 91,
                    "youtube_title": "Strong Title",
                    "video_path": "/tmp/final_video.mp4",
                    "actual_duration_sec": 60,
                    "topic_strategy": {"score_total": 90, "metric_label": "AWARDS"},
                }
            ],
            "failures": [],
        }

    monkeypatch.setattr(batch_script, "produce_batch", fake_produce_batch)

    exit_code = batch_script.main(["--count", "1", "--report"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PRODUCTION BATCH REPORT" in output
    assert "Strong Title" in output
    assert '"success_count"' not in output


@pytest.mark.asyncio
async def test_produce_batch_writes_review_manifest(monkeypatch, tmp_path):
    from scripts import batch_produce_celebrity_videos as batch_script

    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic = selected_topic(1)
    strategy = FakeStrategy([[topic]])

    async def fake_produce(**kwargs):
        return produced_result(1, kwargs["selected_topic"])

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
    )

    manifest_path = Path(summary["manifest_path"])
    manifest = json.loads(manifest_path.read_text())

    assert manifest_path.is_file()
    assert manifest_path.parent == tmp_path / "batches"
    assert manifest["batch_id"] == summary["batch_id"]
    assert manifest["items"][0]["review_id"] == "review-1"
    assert manifest["items"][0]["metadata_score"] == 86.5
    assert manifest["items"][0]["quality_status"] == "passed"
    get_settings.cache_clear()


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
    assert "--max-attempts" in result.stdout
    assert "--duration-profile" in result.stdout
    assert "--target-duration" in result.stdout
    assert "--stop-on-error" in result.stdout
    assert "--no-write-artifacts" in result.stdout
    assert "--report" in result.stdout
