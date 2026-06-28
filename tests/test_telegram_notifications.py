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


@pytest.mark.asyncio
async def test_send_telegram_message_returns_false_on_provider_error(monkeypatch):
    from services import telegram_notifications

    class FakeSettings:
        telegram_bot_token = "token"
        telegram_chat_id = "456"

    class FakeResponse:
        def raise_for_status(self):
            import httpx

            request = httpx.Request("POST", "https://api.telegram.org/botTOKEN/sendMessage")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr(telegram_notifications, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(telegram_notifications.httpx, "AsyncClient", FakeClient)

    sent = await telegram_notifications.send_telegram_message(chat_id=123, text="hello")

    assert sent is False


def test_build_review_keyboard_contains_video_and_review_actions(monkeypatch):
    from services import telegram_notifications

    class FakeSettings:
        public_base_url = "https://example.test"

    monkeypatch.setattr(telegram_notifications, "get_settings", lambda: FakeSettings())

    keyboard = telegram_notifications.build_review_keyboard("review-1")

    assert keyboard["inline_keyboard"][0][0] == {
        "text": "Preview video",
        "url": "https://example.test/api/reviews/review-1/video",
    }
    assert keyboard["inline_keyboard"][0][1] == {
        "text": "Review UI",
        "url": "https://example.test/review-ui",
    }
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == "rv:ok:review-1"
    assert keyboard["inline_keyboard"][2][0]["callback_data"] == "rv:rej:wrong_image:review-1"


def test_build_review_keyboard_omits_invalid_localhost_url(monkeypatch):
    from services import telegram_notifications

    class FakeSettings:
        public_base_url = "http://localhost:8000"

    monkeypatch.setattr(telegram_notifications, "get_settings", lambda: FakeSettings())

    keyboard = telegram_notifications.build_review_keyboard("review-1")

    assert keyboard["inline_keyboard"][0][0] == {
        "text": "Approve and choose channel",
        "callback_data": "rv:ok:review-1",
    }
    assert all("url" not in button for row in keyboard["inline_keyboard"] for button in row)


@pytest.mark.asyncio
async def test_answer_callback_query_posts_ack(monkeypatch):
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

    sent = await telegram_notifications.answer_callback_query(callback_query_id="cb-1", text="Approved")

    assert sent is True
    assert captured["json"]["callback_query_id"] == "cb-1"
    assert captured["json"]["text"] == "Approved"
