import pytest


@pytest.mark.asyncio
async def test_handle_update_routes_message_to_command_handler(monkeypatch):
    from scripts import telegram_remote_bot

    sent = {}

    async def fake_handle_telegram_command(*, telegram_user_id, username, text):
        assert telegram_user_id == 111
        assert username == "alice"
        assert text == "/status"
        return "status response"

    async def fake_send_message(*, chat_id, text):
        sent["chat_id"] = chat_id
        sent["text"] = text
        return True

    async def fake_update_user_chat_id(*, telegram_user_id, chat_id):
        sent["remembered_user_id"] = telegram_user_id
        sent["remembered_chat_id"] = chat_id

    monkeypatch.setattr(telegram_remote_bot, "handle_telegram_command", fake_handle_telegram_command)
    monkeypatch.setattr(telegram_remote_bot, "send_message", fake_send_message)
    monkeypatch.setattr(
        telegram_remote_bot.production_tasks,
        "update_user_chat_id",
        fake_update_user_chat_id,
    )

    handled = await telegram_remote_bot.handle_update(
        {
            "message": {
                "chat": {"id": 999},
                "from": {"id": 111, "username": "alice"},
                "text": "/status",
            }
        }
    )

    assert handled is True
    assert sent == {
        "chat_id": 999,
        "text": "status response",
        "remembered_user_id": 111,
        "remembered_chat_id": 999,
    }


@pytest.mark.asyncio
async def test_handle_update_ignores_non_text_updates():
    from scripts import telegram_remote_bot

    assert await telegram_remote_bot.handle_update({"callback_query": {}}) is False
