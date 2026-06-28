import pytest


def test_parse_review_callback_accepts_approve_and_reject():
    from services.telegram_review_actions import parse_review_callback

    assert parse_review_callback("rv:ok:review-1") == ("approve", "", "review-1")
    assert parse_review_callback("rv:rej:wrong_image:review-1") == ("reject", "wrong_image", "review-1")
    assert parse_review_callback("bad") is None


@pytest.mark.asyncio
async def test_handle_review_callback_approves_authorized_user(monkeypatch):
    from services import telegram_review_actions

    calls = {}

    async def fake_get_authorized_user(user_id):
        assert user_id == 111
        return {"telegram_user_id": 111, "role": "producer", "is_active": True}

    async def fake_approve_and_enqueue(**kwargs):
        calls["approve"] = kwargs
        return {"upload_job_id": "upload-1", "status": "queued"}

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        fake_get_authorized_user,
    )
    monkeypatch.setattr(
        telegram_review_actions.youtube_upload_jobs,
        "approve_and_enqueue",
        fake_approve_and_enqueue,
    )

    response = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:ok:review-1",
    )

    assert response == "Approved and queued upload upload-1."
    assert calls["approve"] == {
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
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

    assert response == "Rejected review review-1: bad_fact."
    assert calls["reject"] == {
        "review_id": "review-1",
        "reason": "bad_fact",
        "notes": "rejected from Telegram: bad_fact",
    }
    assert calls["decision"] == {"review_id": "review-1", "status": "rejected"}
