from unittest.mock import AsyncMock

import pytest


def test_parse_review_callback_accepts_approve_and_reject():
    from services.telegram_review_actions import parse_review_callback

    assert parse_review_callback("rv:ok:review-1") == ("approve", "", "review-1")
    assert parse_review_callback("rv:ch:1:review-1") == (
        "approve_channel",
        "1",
        "review-1",
    )
    assert parse_review_callback("rv:rej:wrong_image:review-1") == ("reject", "wrong_image", "review-1")
    assert parse_review_callback("bad") is None


@pytest.mark.asyncio
async def test_handle_review_callback_approve_requires_explicit_channel(monkeypatch):
    from services import telegram_review_actions

    async def fake_get_authorized_user(user_id):
        assert user_id == 111
        return {"telegram_user_id": 111, "role": "producer", "is_active": True}

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        fake_get_authorized_user,
    )
    async def fake_list_owned_channels(user_id):
        return [
            {"youtube_channel_id": "channel-1", "title": "Main Channel", "status": "active"},
            {"youtube_channel_id": "channel-2", "title": "Backup Channel", "status": "active"},
        ]

    monkeypatch.setattr(
        telegram_review_actions.youtube_channels,
        "list_owned_channels",
        fake_list_owned_channels,
    )

    response = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:ok:review-1",
    )

    assert response.reply_markup["inline_keyboard"][0][0]["text"] == "Main Channel"
    assert response.reply_markup["inline_keyboard"][0][0]["callback_data"] == "rv:ch:1:review-1"
    assert len(response.reply_markup["inline_keyboard"][0][0]["callback_data"]) <= 64
    assert "chọn kênh youtube" in response.text.lower()


@pytest.mark.asyncio
async def test_handle_review_callback_channel_choice_approves_and_queues(monkeypatch):
    from services import telegram_review_actions

    calls = {}

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": 111, "role": "producer", "is_active": True}

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        fake_get_authorized_user,
    )

    async def fake_approve_and_enqueue(**kwargs):
        calls["approve"] = kwargs
        return {"upload_job_id": "upload-1", "status": "queued"}

    monkeypatch.setattr(
        telegram_review_actions.youtube_upload_jobs,
        "approve_and_enqueue",
        fake_approve_and_enqueue,
    )
    async def fake_list_owned_channels(user_id):
        return [
            {"youtube_channel_id": "channel-1", "title": "Main Channel", "status": "active"},
            {"youtube_channel_id": "channel-2", "title": "Backup Channel", "status": "active"},
        ]

    monkeypatch.setattr(
        telegram_review_actions.youtube_channels,
        "list_owned_channels",
        fake_list_owned_channels,
    )

    response = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:ch:1:review-1",
    )

    assert "upload-1" not in response
    assert "đã approve video" in response.lower()
    assert "main channel" in response.lower()
    assert calls["approve"] == {
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
        "youtube_channel_id": "channel-1",
    }


@pytest.mark.asyncio
async def test_handle_review_callback_rejects_authorized_user(monkeypatch):
    from services import telegram_review_actions

    calls = {}

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": 111, "role": "producer", "is_active": True}

    async def fake_reject_review(review_id, reason="", notes=""):
        calls["reject"] = {"review_id": review_id, "reason": reason, "notes": notes}
        return {"review_id": review_id, "status": "rejected"}

    async def fake_mark_task_review_decision(**kwargs):
        calls["decision"] = kwargs

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        fake_get_authorized_user,
    )
    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "assert_review_owner",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(telegram_review_actions, "reject_review", fake_reject_review)
    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "mark_task_review_decision",
        fake_mark_task_review_decision,
    )

    response = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:rej:bad_fact:review-1",
    )

    assert "review-1" not in response
    assert "đã reject video" in response.lower()
    assert "dữ kiện" in response.lower()
    assert calls["reject"] == {
        "review_id": "review-1",
        "reason": "bad_fact",
        "notes": "rejected from Telegram: bad_fact",
    }
    assert calls["decision"] == {"review_id": "review-1", "status": "rejected"}


@pytest.mark.asyncio
async def test_handle_review_callback_reject_blocks_other_users_review(monkeypatch):
    from services import telegram_review_actions

    async def fake_get_authorized_user(user_id):
        return {"telegram_user_id": 111, "role": "producer", "is_active": True}

    async def fake_reject_review(*args, **kwargs):
        raise AssertionError("must not reject another user's review")

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        fake_get_authorized_user,
    )
    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "assert_review_owner",
        AsyncMock(side_effect=PermissionError("Review is unavailable")),
        raising=False,
    )
    monkeypatch.setattr(telegram_review_actions, "reject_review", fake_reject_review)

    response = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:rej:bad_fact:review-owned-by-222",
    )

    assert response == "Review or YouTube channel is unavailable."
