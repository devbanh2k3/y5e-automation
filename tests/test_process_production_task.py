import pytest


def test_completion_message_reports_degraded_card_counts_without_internal_ids():
    from scripts.process_production_task import build_production_completion_message

    text = build_production_completion_message(
        title="Celebrity Records",
        layout="flag_hero",
        target_duration=180,
        summary={
            "target_cards": 58,
            "final_cards": 55,
            "skipped_cards": 3,
            "degraded": True,
        },
    )

    assert "55/58 card" in text
    assert "3 card" in text
    assert "task_id" not in text


def test_failure_message_hides_raw_ai_error():
    from core.ai_resilience import AIJsonFailure
    from scripts.process_production_task import build_production_failure_message

    text = build_production_failure_message(
        AIJsonFailure("raw malformed payload", category="json_exhausted", attempts=3)
    )

    assert "AI trả dữ liệu không hợp lệ" in text
    assert "raw malformed payload" not in text


@pytest.mark.asyncio
async def test_progress_callback_reports_counts_and_ignores_notification_failure(monkeypatch):
    from scripts import process_production_task

    messages = []

    async def fake_notify(**kwargs):
        messages.append(kwargs["text"])
        raise RuntimeError("Telegram unavailable")

    monkeypatch.setattr(process_production_task, "_notify_owner", fake_notify)
    callback = process_production_task.build_progress_callback(
        owner_telegram_user_id=42,
        minimum_interval=0,
    )

    await callback(
        {
            "stage": "image_verification",
            "ready": 43,
            "target": 54,
            "repairing": 2,
        }
    )

    assert messages == ["Đang xác minh hình ảnh: 43/54 card\nĐang sửa: 2"]


@pytest.mark.asyncio
async def test_process_one_task_claims_fair_task_and_marks_pending_review(monkeypatch):
    from scripts import process_production_task

    calls = {}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
            "target_duration": 90,
        }

    async def fake_produce(**kwargs):
        calls["produce"] = kwargs
        return {
            "review_id": "review-1",
            "topic_id": "topic-1",
            "video_path": "/tmp/final.mp4",
        }

    async def fake_mark_task_pending_review(**kwargs):
        calls["pending"] = kwargs

    class FakeRepository:
        def mark_produced(self, reservation_id, *, topic_id):
            calls["topic_produced"] = {"reservation_id": reservation_id, "topic_id": topic_id}

        def mark_failed(self, reservation_id, *, reason):
            calls["topic_failed"] = {"reservation_id": reservation_id, "reason": reason}

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            calls["topic_run"] = {"count": count, "language": language, "batch_id": batch_id}
            return [{"reservation_id": "reservation-1", "title": "Distinct topic"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "mark_task_pending_review",
        fake_mark_task_pending_review,
    )
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "pending_review"
    assert calls["produce"]["language"] == "en"
    assert calls["produce"]["card_layout"] == "flag_hero"
    assert calls["produce"]["selected_topic"]["reservation_id"] == "reservation-1"
    assert calls["produce"]["target_duration"] == 90
    assert calls["topic_run"]["count"] == 1
    assert calls["topic_produced"] == {"reservation_id": "reservation-1", "topic_id": "topic-1"}
    assert calls["pending"]["task_id"] == "task-1"
    assert calls["pending"]["review_id"] == "review-1"
    assert calls["notification"]["chat_id"] == 999
    assert "sẵn sàng duyệt" in calls["notification"]["text"].lower()
    assert "review-1" not in calls["notification"]["text"]
    assert any(
            button.get("text") == "Approve and choose channel"
        for row in calls["notification"]["reply_markup"]["inline_keyboard"]
        for button in row
    )


@pytest.mark.asyncio
async def test_process_one_task_marks_failure(monkeypatch):
    from scripts import process_production_task

    calls = {}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
        }

    async def fake_produce(**kwargs):
        raise RuntimeError("render failed")

    async def fake_mark_task_failed(**kwargs):
        calls["failed"] = kwargs

    class FakeRepository:
        def mark_failed(self, reservation_id, *, reason):
            calls["topic_failed"] = {"reservation_id": reservation_id, "reason": reason}

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            return [{"reservation_id": "reservation-1", "title": "Distinct topic"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(process_production_task.production_tasks, "mark_task_failed", fake_mark_task_failed)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "failed"
    assert calls["failed"]["task_id"] == "task-1"
    assert "render failed" in calls["failed"]["error"]
    assert calls["topic_failed"]["reservation_id"] == "reservation-1"
    assert calls["notification"]["chat_id"] == 999
    assert "thất bại" in calls["notification"]["text"].lower()
    assert "render failed" not in calls["notification"]["text"].lower()


@pytest.mark.asyncio
async def test_process_one_task_replaces_fact_rejected_topic(monkeypatch):
    from core.fact_verification import FactVerificationError
    from scripts import process_production_task

    calls = {"topic_runs": [], "produce": []}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
            "target_duration": 60,
        }

    async def fake_produce(**kwargs):
        calls["produce"].append(kwargs)
        if len(calls["produce"]) == 1:
            raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")
        return {
            "review_id": "review-2",
            "topic_id": "topic-2",
            "video_path": "/tmp/final-2.mp4",
            "youtube_title": "Better factual topic",
            "target_duration": 60,
        }

    async def fake_mark_task_pending_review(**kwargs):
        calls["pending"] = kwargs

    async def fake_mark_task_failed(**kwargs):
        calls["task_failed"] = kwargs

    class FakeRepository:
        def mark_produced(self, reservation_id, *, topic_id):
            calls["topic_produced"] = {"reservation_id": reservation_id, "topic_id": topic_id}

        def mark_failed(self, reservation_id, *, reason):
            calls.setdefault("topic_failed", []).append(
                {"reservation_id": reservation_id, "reason": reason}
            )

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            calls["topic_runs"].append({"count": count, "language": language, "batch_id": batch_id})
            reservation = len(calls["topic_runs"])
            return [{"reservation_id": f"reservation-{reservation}", "title": f"Topic {reservation}"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "mark_task_pending_review",
        fake_mark_task_pending_review,
    )
    monkeypatch.setattr(process_production_task.production_tasks, "mark_task_failed", fake_mark_task_failed)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "pending_review"
    assert len(calls["topic_runs"]) == 2
    assert len(calls["produce"]) == 2
    assert calls["produce"][1]["selected_topic"]["reservation_id"] == "reservation-2"
    assert calls["topic_failed"][0]["reservation_id"] == "reservation-1"
    assert calls["topic_produced"] == {"reservation_id": "reservation-2", "topic_id": "topic-2"}
    assert calls["pending"]["review_id"] == "review-2"
    assert "task_failed" not in calls
    assert "sẵn sàng duyệt" in calls["notification"]["text"].lower()


@pytest.mark.asyncio
async def test_process_one_task_retries_topic_reservation_race(monkeypatch):
    from agents.topic_strategy_agent import TopicSelectionError
    from scripts import process_production_task

    calls = {"topic_runs": [], "produce": []}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
            "target_duration": 60,
        }

    async def fake_produce(**kwargs):
        calls["produce"].append(kwargs)
        return {
            "review_id": "review-2",
            "topic_id": "topic-2",
            "video_path": "/tmp/final-2.mp4",
            "youtube_title": "Recovered topic",
            "target_duration": 60,
        }

    async def fake_mark_task_pending_review(**kwargs):
        calls["pending"] = kwargs

    async def fake_mark_task_failed(**kwargs):
        calls["task_failed"] = kwargs

    class FakeRepository:
        def mark_produced(self, reservation_id, *, topic_id):
            calls["topic_produced"] = {"reservation_id": reservation_id, "topic_id": topic_id}

        def mark_failed(self, reservation_id, *, reason):
            calls.setdefault("topic_failed", []).append(
                {"reservation_id": reservation_id, "reason": reason}
            )

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            calls["topic_runs"].append({"count": count, "language": language, "batch_id": batch_id})
            if len(calls["topic_runs"]) == 1:
                raise TopicSelectionError("topic reservations changed concurrently")
            return [{"reservation_id": "reservation-2", "title": "Topic 2"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "mark_task_pending_review",
        fake_mark_task_pending_review,
    )
    monkeypatch.setattr(process_production_task.production_tasks, "mark_task_failed", fake_mark_task_failed)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "pending_review"
    assert len(calls["topic_runs"]) == 2
    assert len(calls["produce"]) == 1
    assert calls["produce"][0]["selected_topic"]["reservation_id"] == "reservation-2"
    assert calls["topic_produced"] == {"reservation_id": "reservation-2", "topic_id": "topic-2"}
    assert calls["pending"]["review_id"] == "review-2"
    assert "task_failed" not in calls


@pytest.mark.asyncio
async def test_process_one_task_replaces_missing_real_image_topic(monkeypatch):
    from scripts import process_production_task

    calls = {"topic_runs": [], "produce": []}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
            "target_duration": 60,
        }

    async def fake_produce(**kwargs):
        calls["produce"].append(kwargs)
        if len(calls["produce"]) == 1:
            raise ValueError("missing verified real images: Coen Brothers (Joel)")
        return {
            "review_id": "review-2",
            "topic_id": "topic-2",
            "video_path": "/tmp/final-2.mp4",
            "youtube_title": "Better image topic",
            "target_duration": 60,
        }

    async def fake_mark_task_pending_review(**kwargs):
        calls["pending"] = kwargs

    async def fake_mark_task_failed(**kwargs):
        calls["task_failed"] = kwargs

    class FakeRepository:
        def mark_produced(self, reservation_id, *, topic_id):
            calls["topic_produced"] = {"reservation_id": reservation_id, "topic_id": topic_id}

        def mark_failed(self, reservation_id, *, reason):
            calls.setdefault("topic_failed", []).append(
                {"reservation_id": reservation_id, "reason": reason}
            )

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            calls["topic_runs"].append({"count": count, "language": language, "batch_id": batch_id})
            reservation = len(calls["topic_runs"])
            return [{"reservation_id": f"reservation-{reservation}", "title": f"Topic {reservation}"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "mark_task_pending_review",
        fake_mark_task_pending_review,
    )
    monkeypatch.setattr(process_production_task.production_tasks, "mark_task_failed", fake_mark_task_failed)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "pending_review"
    assert len(calls["topic_runs"]) == 2
    assert len(calls["produce"]) == 2
    assert calls["produce"][1]["selected_topic"]["reservation_id"] == "reservation-2"
    assert calls["topic_failed"][0]["reservation_id"] == "reservation-1"
    assert "Coen Brothers" in calls["topic_failed"][0]["reason"]
    assert calls["topic_produced"] == {"reservation_id": "reservation-2", "topic_id": "topic-2"}
    assert calls["pending"]["review_id"] == "review-2"
    assert "task_failed" not in calls


@pytest.mark.asyncio
async def test_process_one_task_replaces_duplicate_content_topic(monkeypatch):
    from scripts import process_production_task

    calls = {"topic_runs": [], "produce": []}

    async def fake_claim_next_fair_task():
        return {
            "task_id": "task-1",
            "batch_id": "batch-1",
            "owner_telegram_user_id": 111,
            "slot_index": 1,
            "target_duration": 180,
        }

    async def fake_produce(**kwargs):
        calls["produce"].append(kwargs)
        if len(calls["produce"]) == 1:
            raise ValueError("duplicate celebrity scenes: St. Vincent")
        return {
            "review_id": "review-2",
            "topic_id": "topic-2",
            "video_path": "/tmp/final-2.mp4",
            "youtube_title": "Better unique topic",
            "target_duration": 180,
        }

    async def fake_mark_task_pending_review(**kwargs):
        calls["pending"] = kwargs

    async def fake_mark_task_failed(**kwargs):
        calls["task_failed"] = kwargs

    class FakeRepository:
        def mark_produced(self, reservation_id, *, topic_id):
            calls["topic_produced"] = {"reservation_id": reservation_id, "topic_id": topic_id}

        def mark_failed(self, reservation_id, *, reason):
            calls.setdefault("topic_failed", []).append(
                {"reservation_id": reservation_id, "reason": reason}
            )

    class FakeTopicStrategyAgent:
        def __init__(self):
            self.repository = FakeRepository()

        async def run(self, *, count, language, batch_id):
            calls["topic_runs"].append({"count": count, "language": language, "batch_id": batch_id})
            reservation = len(calls["topic_runs"])
            return [{"reservation_id": f"reservation-{reservation}", "title": f"Topic {reservation}"}]

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text, reply_markup=None):
        calls["notification"] = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
    monkeypatch.setattr(process_production_task, "TopicStrategyAgent", FakeTopicStrategyAgent)
    monkeypatch.setattr(process_production_task, "produce", fake_produce)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "mark_task_pending_review",
        fake_mark_task_pending_review,
    )
    monkeypatch.setattr(process_production_task.production_tasks, "mark_task_failed", fake_mark_task_failed)
    monkeypatch.setattr(
        process_production_task.production_tasks,
        "get_notification_chat_id",
        fake_get_notification_chat_id,
    )
    monkeypatch.setattr(process_production_task, "send_telegram_message", fake_send_telegram_message)

    result = await process_production_task.process_one_task()

    assert result["status"] == "pending_review"
    assert len(calls["topic_runs"]) == 2
    assert len(calls["produce"]) == 2
    assert calls["produce"][1]["selected_topic"]["reservation_id"] == "reservation-2"
    assert calls["topic_failed"][0]["reservation_id"] == "reservation-1"
    assert "St. Vincent" in calls["topic_failed"][0]["reason"]
    assert calls["topic_produced"] == {"reservation_id": "reservation-2", "topic_id": "topic-2"}
    assert calls["pending"]["review_id"] == "review-2"
    assert "task_failed" not in calls


@pytest.mark.asyncio
async def test_process_one_task_returns_idle_when_no_task(monkeypatch):
    from scripts import process_production_task

    async def fake_claim_next_fair_task():
        return None

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)

    result = await process_production_task.process_one_task()

    assert result == {"status": "idle"}
