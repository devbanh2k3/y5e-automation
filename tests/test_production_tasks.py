import pytest


@pytest.mark.asyncio
async def test_create_batch_creates_one_task_per_requested_video(monkeypatch):
    from core import production_tasks

    calls = {"execute": [], "fetchval": 0}

    async def fake_fetchval(query, *args):
        calls["fetchval"] += 1
        return "batch-1"

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))
        return "INSERT 0 1"

    async def fake_fetchrow(query, *args):
        return {"youtube_channel_id": "channel-1", "title": "Alice Channel"}

    monkeypatch.setattr(production_tasks, "fetchval", fake_fetchval)
    monkeypatch.setattr(production_tasks, "execute", fake_execute)
    monkeypatch.setattr(production_tasks, "fetchrow", fake_fetchrow)

    batch = await production_tasks.create_production_batch(
        owner_telegram_user_id=111,
        requested_count=3,
        language="en",
        card_layout="flag_hero",
        category="celebrity",
        target_duration=90,
        youtube_channel_id="channel-1",
    )

    assert batch["batch_id"] == "batch-1"
    assert batch["requested_count"] == 3
    assert batch["target_duration"] == 90
    assert batch["youtube_channel_id"] == "channel-1"
    assert calls["fetchval"] == 1
    task_inserts = [call for call in calls["execute"] if "production_tasks" in call[0]]
    assert len(task_inserts) == 3
    assert all(call[1][0] == "batch-1" for call in task_inserts)
    assert all(call[1][1] == 111 for call in task_inserts)


@pytest.mark.asyncio
async def test_create_batch_rejects_channel_owned_by_another_user(monkeypatch):
    from core import production_tasks

    async def fake_fetchrow(query, *args):
        return None

    monkeypatch.setattr(production_tasks, "fetchrow", fake_fetchrow)

    with pytest.raises(PermissionError):
        await production_tasks.create_production_batch(
            owner_telegram_user_id=111,
            youtube_channel_id="channel-of-user-222",
            requested_count=1,
        )


@pytest.mark.asyncio
async def test_claim_next_fair_task_uses_least_recently_served_user(monkeypatch):
    from core import production_tasks

    rows = [
        {
            "owner_telegram_user_id": 222,
            "last_served_at": None,
            "oldest_task_created_at": "2026-06-28T00:00:00+00:00",
        },
        {
            "owner_telegram_user_id": 111,
            "last_served_at": "2026-06-28T00:05:00+00:00",
            "oldest_task_created_at": "2026-06-28T00:01:00+00:00",
        },
    ]
    fetchrow_calls = []

    async def fake_fetch(query, *args):
        return rows

    async def fake_fetchrow(query, *args):
        fetchrow_calls.append(args)
        if "FROM production_batches" in query:
            assert args[0] == "batch-b"
            return {
                "category": "celebrity",
                "language": "en",
                "card_layout": "flag_hero",
                "target_duration": 90,
            }
        assert args[0] == 222
        return {
            "task_id": "task-b1",
            "batch_id": "batch-b",
            "owner_telegram_user_id": 222,
            "status": "running",
        }

    async def fake_execute(query, *args):
        return "INSERT 0 1"

    monkeypatch.setattr(production_tasks, "fetch", fake_fetch)
    monkeypatch.setattr(production_tasks, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(production_tasks, "execute", fake_execute)

    task = await production_tasks.claim_next_fair_task()

    assert task["task_id"] == "task-b1"
    assert task["owner_telegram_user_id"] == 222
    assert task["language"] == "en"
    assert task["target_duration"] == 90


@pytest.mark.asyncio
async def test_authorized_user_requires_active_record(monkeypatch):
    from core import production_tasks

    async def fake_fetchrow(query, *args):
        if args[0] == 111:
            return {"telegram_user_id": 111, "role": "producer", "is_active": True}
        return None

    monkeypatch.setattr(production_tasks, "fetchrow", fake_fetchrow)

    assert await production_tasks.get_authorized_user(111) == {
        "telegram_user_id": 111,
        "role": "producer",
        "is_active": True,
    }
    assert await production_tasks.get_authorized_user(222) is None


@pytest.mark.asyncio
async def test_complete_task_records_review_and_updates_batch(monkeypatch):
    from core import production_tasks

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(production_tasks, "execute", fake_execute)

    await production_tasks.mark_task_pending_review(
        task_id="task-1",
        batch_id="batch-1",
        review_id="review-1",
        topic_id="topic-1",
        video_path="/tmp/final.mp4",
    )

    assert any("pending_review" in call[0] for call in calls)
    assert any("completed_count" in call[0] for call in calls)


@pytest.mark.asyncio
async def test_fail_task_records_error_and_updates_batch(monkeypatch):
    from core import production_tasks

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(production_tasks, "execute", fake_execute)

    await production_tasks.mark_task_failed(
        task_id="task-1",
        batch_id="batch-1",
        error="render failed",
    )

    assert any("failed" in call[0] for call in calls)
    assert any("failed_count" in call[0] for call in calls)


@pytest.mark.asyncio
async def test_mark_task_review_decision_updates_task_status(monkeypatch):
    from core import production_tasks

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(production_tasks, "execute", fake_execute)

    await production_tasks.mark_task_review_decision(review_id="review-1", status="approved")

    assert calls[0][1] == ("review-1", "approved")
