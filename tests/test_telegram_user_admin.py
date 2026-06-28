import pytest


@pytest.mark.asyncio
async def test_allow_user_upserts_active_telegram_user(monkeypatch):
    from scripts import telegram_user_admin

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "INSERT 0 1"

    monkeypatch.setattr(telegram_user_admin, "execute", fake_execute)

    result = await telegram_user_admin.allow_user(
        telegram_user_id=111,
        username="alice",
        role="producer",
    )

    assert result["telegram_user_id"] == 111
    assert result["role"] == "producer"
    assert calls[0][1] == (111, "alice", "producer")


@pytest.mark.asyncio
async def test_disable_user_marks_inactive(monkeypatch):
    from scripts import telegram_user_admin

    calls = []

    async def fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(telegram_user_admin, "execute", fake_execute)

    result = await telegram_user_admin.disable_user(telegram_user_id=111)

    assert result == {"telegram_user_id": 111, "is_active": False}
    assert calls[0][1] == (111,)
