import pytest


@pytest.mark.asyncio
async def test_start_rejects_unauthorized_user(monkeypatch):
    from services import telegram_remote

    async def fake_get_authorized_user(user_id):
        return None

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/start",
    )

    assert "not authorized" in response.lower()


@pytest.mark.asyncio
async def test_create_command_creates_batch_without_quota(monkeypatch):
    from services import telegram_remote

    captured = {}

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    async def fake_create_production_batch(**kwargs):
        captured.update(kwargs)
        return {
            "batch_id": "batch-1",
            "requested_count": kwargs["requested_count"],
            "language": kwargs["language"],
            "card_layout": kwargs["card_layout"],
            "category": kwargs["category"],
        }

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "create_production_batch", fake_create_production_batch)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 10 celebrity en flag_hero",
    )

    assert captured == {
        "owner_telegram_user_id": 111,
        "requested_count": 10,
        "category": "celebrity",
        "language": "en",
        "card_layout": "flag_hero",
    }
    assert "batch-1" in response
    assert "10 tasks queued" in response
    assert "fair queue" in response.lower()


@pytest.mark.asyncio
async def test_create_command_rejects_unsupported_category(monkeypatch):
    from services import telegram_remote

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    async def fake_create_production_batch(**kwargs):
        raise AssertionError("unsupported categories must not create batches")

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "create_production_batch", fake_create_production_batch)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 10 world en flag_hero",
    )

    assert "only category 'celebrity'" in response.lower()


@pytest.mark.asyncio
async def test_create_command_enforces_per_command_max_not_daily_quota(monkeypatch):
    from services import telegram_remote

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 25 celebrity en flag_hero",
    )

    assert "max per command is 20" in response.lower()
    assert "daily quota" not in response.lower()


@pytest.mark.asyncio
async def test_status_returns_user_queue_summary(monkeypatch):
    from services import telegram_remote

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    async def fake_user_queue_summary(user_id):
        return {"queued": 6, "running": 1, "pending_review": 3, "failed": 0}

    async def fake_list_user_batches(user_id, limit=5):
        return [
            {
                "batch_id": "batch-1",
                "requested_count": 10,
                "completed_count": 3,
                "failed_count": 0,
                "status": "running",
            }
        ]

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "user_queue_summary", fake_user_queue_summary)
    monkeypatch.setattr(telegram_remote.production_tasks, "list_user_batches", fake_list_user_batches)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/status",
    )

    assert "queued: 6" in response.lower()
    assert "running: 1" in response.lower()
    assert "batch-1" in response
