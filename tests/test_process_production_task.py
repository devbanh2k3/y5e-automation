import pytest


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

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text):
        calls["notification"] = {"chat_id": chat_id, "text": text}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
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
    assert calls["pending"]["task_id"] == "task-1"
    assert calls["pending"]["review_id"] == "review-1"
    assert calls["notification"]["chat_id"] == 999
    assert "ready for review" in calls["notification"]["text"].lower()


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

    async def fake_get_notification_chat_id(user_id):
        assert user_id == 111
        return 999

    async def fake_send_telegram_message(*, chat_id, text):
        calls["notification"] = {"chat_id": chat_id, "text": text}
        return True

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)
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
    assert calls["notification"]["chat_id"] == 999
    assert "failed" in calls["notification"]["text"].lower()


@pytest.mark.asyncio
async def test_process_one_task_returns_idle_when_no_task(monkeypatch):
    from scripts import process_production_task

    async def fake_claim_next_fair_task():
        return None

    monkeypatch.setattr(process_production_task.production_tasks, "claim_next_fair_task", fake_claim_next_fair_task)

    result = await process_production_task.process_one_task()

    assert result == {"status": "idle"}
