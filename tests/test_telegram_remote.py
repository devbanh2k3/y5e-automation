from unittest.mock import AsyncMock

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
            "target_duration": kwargs["target_duration"],
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
        "target_duration": 60,
    }
    assert "batch-1" not in response
    assert "số lượng: 10 video" in response.lower()
    assert "thời lượng mục tiêu: 60" in response.lower()
    assert "queue công bằng" in response.lower()


@pytest.mark.asyncio
async def test_create_command_accepts_duration_option(monkeypatch):
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
            "target_duration": kwargs["target_duration"],
        }

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "create_production_batch", fake_create_production_batch)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 2 celebrity en flag_hero --duration 90",
    )

    assert captured["target_duration"] == 90
    assert "thời lượng mục tiêu: 90" in response.lower()


@pytest.mark.asyncio
async def test_create_command_accepts_longer_duration(monkeypatch):
    from services import telegram_remote

    captured = {}

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    async def fake_create_production_batch(**kwargs):
        captured.update(kwargs)
        return {
            "batch_id": "batch-1",
            "requested_count": kwargs["requested_count"],
            "target_duration": kwargs["target_duration"],
        }

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "create_production_batch", fake_create_production_batch)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 2 celebrity en flag_hero --duration 300",
    )

    assert captured["target_duration"] == 300
    assert "300 giây/video" in response


@pytest.mark.asyncio
async def test_create_command_rejects_too_large_duration(monkeypatch):
    from services import telegram_remote

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": user_id, "username": "alice", "role": "producer", "is_active": True}

    async def fake_create_production_batch(**kwargs):
        raise AssertionError("invalid duration must not create batches")

    monkeypatch.setattr(telegram_remote.production_tasks, "get_authorized_user", fake_get_authorized_user)
    monkeypatch.setattr(telegram_remote.production_tasks, "create_production_batch", fake_create_production_batch)

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        username="alice",
        text="/create 2 celebrity en flag_hero --duration 601",
    )

    assert "between 15 and 600 seconds" in response.lower()


@pytest.mark.asyncio
async def test_create_does_not_require_channel_before_render(monkeypatch):
    from services import telegram_remote

    captured = {}

    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "create_production_batch",
        AsyncMock(side_effect=lambda **kwargs: captured.update(kwargs) or {
            "batch_id": "batch-1",
            "requested_count": kwargs["requested_count"],
            "target_duration": kwargs["target_duration"],
        }),
    )

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        text="/create 1",
    )

    assert captured["requested_count"] == 1
    assert "batch-1" not in response
    assert "đã nhận yêu cầu" in response.lower()


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
        return {"queued": 6, "running": 1, "pending_review": 3, "approved": 2, "rejected": 1, "failed": 0}

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

    assert "đang chờ: 6" in response.lower()
    assert "đang render: 1" in response.lower()
    assert "đã approve: 2" in response.lower()
    assert "đã reject: 1" in response.lower()
    assert "batch-1" not in response


@pytest.mark.asyncio
async def test_reviews_lists_pending_videos_with_preview_and_approve(monkeypatch):
    from services import telegram_remote

    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "list_pending_review_tasks",
        AsyncMock(
            return_value=[
                {
                    "review_id": "review-1",
                    "topic_id": "topic-1",
                    "video_path": "/app/output/video.mp4",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        telegram_remote,
        "get_settings",
        lambda: type("S", (), {"public_base_url": "https://example.test"})(),
    )

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        text="/reviews",
    )

    assert "video chờ duyệt" in response.text.lower()
    assert "review-1" not in response.text
    buttons = response.reply_markup["inline_keyboard"][0]
    assert buttons[0] == {
        "text": "Preview 1",
        "url": "https://example.test/api/reviews/review-1/video",
    }
    assert buttons[1] == {
        "text": "Approve 1",
        "callback_data": "rv:ok:review-1",
    }


@pytest.mark.asyncio
async def test_reviews_uses_youtube_title_from_review_artifact(monkeypatch):
    from services import telegram_remote

    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "list_pending_review_tasks",
        AsyncMock(return_value=[{"review_id": "review-1", "video_path": "/app/output/video.mp4"}]),
    )
    monkeypatch.setattr(
        telegram_remote,
        "get_review",
        AsyncMock(return_value={"youtube": {"title": "Celebrity Net Worth Gap That Feels Unreal"}}),
    )
    monkeypatch.setattr(
        telegram_remote,
        "get_settings",
        lambda: type("S", (), {"public_base_url": "https://example.test"})(),
    )

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        text="/reviews",
    )

    assert "Celebrity Net Worth Gap That Feels Unreal" in response.text
    assert "Video #1" not in response.text


@pytest.mark.asyncio
async def test_reviews_handles_empty_pending_list(monkeypatch):
    from services import telegram_remote

    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "list_pending_review_tasks",
        AsyncMock(return_value=[]),
    )

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        text="/reviews",
    )

    assert response.text == "Hiện không có video nào chờ duyệt."
    assert response.reply_markup is None


@pytest.mark.asyncio
async def test_upload_status_lists_only_owner_jobs(monkeypatch):
    from services import telegram_remote

    monkeypatch.setattr(
        telegram_remote.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_remote.youtube_upload_jobs,
        "list_owner_jobs",
        AsyncMock(
            return_value=[
                {
                    "status": "published",
                    "channel_title": "Alice Channel",
                    "youtube_url": "https://youtube.com/watch?v=yt-1",
                    "error_code": "",
                }
            ]
        ),
    )

    response = await telegram_remote.handle_telegram_command(
        telegram_user_id=111,
        text="/uploads",
    )

    assert "Published" in response
    assert "Alice Channel" in response
