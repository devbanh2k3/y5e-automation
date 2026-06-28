import pytest


@pytest.mark.asyncio
async def test_list_chat_ids_extracts_visible_chats(monkeypatch):
    from scripts import telegram_chat_id

    class FakeSettings:
        telegram_bot_token = "token"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "result": [
                    {
                        "message": {
                            "chat": {"id": 123, "type": "private", "username": "alice"},
                            "from": {"id": 123, "username": "alice"},
                        }
                    }
                ],
            }

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 15.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params):
            assert params["timeout"] == 10
            return FakeResponse()

    monkeypatch.setattr(telegram_chat_id, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(telegram_chat_id.httpx, "AsyncClient", FakeClient)

    chats = await telegram_chat_id.list_chat_ids(timeout=10)

    assert chats == [
        {
            "chat_id": 123,
            "chat_type": "private",
            "chat_title": "alice",
            "from_user_id": 123,
            "from_username": "alice",
        }
    ]
