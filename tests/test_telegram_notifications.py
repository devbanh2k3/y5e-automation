import pytest


@pytest.mark.asyncio
async def test_send_telegram_message_skips_without_token(monkeypatch):
    from services import telegram_notifications

    class FakeSettings:
        telegram_bot_token = ""
        telegram_chat_id = "123"

    monkeypatch.setattr(telegram_notifications, "get_settings", lambda: FakeSettings())

    sent = await telegram_notifications.send_telegram_message(chat_id=123, text="hello")

    assert sent is False


@pytest.mark.asyncio
async def test_send_telegram_message_uses_fallback_chat_id(monkeypatch):
    from services import telegram_notifications

    captured = {}

    class FakeSettings:
        telegram_bot_token = "token"
        telegram_chat_id = "456"

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 15.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(telegram_notifications, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(telegram_notifications.httpx, "AsyncClient", FakeClient)

    sent = await telegram_notifications.send_telegram_message(chat_id=None, text="hello")

    assert sent is True
    assert captured["json"]["chat_id"] == 456
    assert captured["json"]["text"] == "hello"
