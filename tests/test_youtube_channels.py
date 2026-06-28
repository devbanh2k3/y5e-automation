from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_get_owned_channel_rejects_another_owner(monkeypatch) -> None:
    from core import youtube_channels

    monkeypatch.setattr(youtube_channels, "fetchrow", AsyncMock(return_value=None))

    with pytest.raises(youtube_channels.ChannelAccessError):
        await youtube_channels.get_owned_channel(
            "b4ff8d8b-14aa-4cf2-b01c-33545c48f46a",
            owner_telegram_user_id=222,
        )


@pytest.mark.asyncio
async def test_consume_oauth_token_is_atomic_and_single_use(monkeypatch) -> None:
    from core import youtube_channels

    fetchrow = AsyncMock(
        side_effect=[{"owner_telegram_user_id": 111}, None]
    )
    monkeypatch.setattr(youtube_channels, "fetchrow", fetchrow)

    assert (
        await youtube_channels.consume_oauth_token("raw", purpose="oauth_state")
        == 111
    )
    with pytest.raises(youtube_channels.OAuthStateError):
        await youtube_channels.consume_oauth_token("raw", purpose="oauth_state")

    query = fetchrow.await_args_list[0].args[0]
    assert "consumed_at IS NULL" in query
    assert "expires_at > NOW()" in query


@pytest.mark.asyncio
async def test_issue_oauth_token_stores_only_hash(monkeypatch) -> None:
    from core import youtube_channels

    execute = AsyncMock(return_value="INSERT 0 1")
    monkeypatch.setattr(youtube_channels, "execute", execute)

    raw = await youtube_channels.issue_oauth_token(
        owner_telegram_user_id=111,
        purpose="connect_ticket",
    )

    args = execute.await_args.args
    assert raw not in args
    assert args[2] == 111
    assert args[3] == "connect_ticket"


@pytest.mark.asyncio
async def test_upsert_channel_encrypts_refresh_token_before_storage(monkeypatch) -> None:
    from core import youtube_channels

    fetchrow = AsyncMock(return_value={"youtube_channel_id": "channel-1"})
    monkeypatch.setattr(youtube_channels, "fetchrow", fetchrow)
    monkeypatch.setattr(youtube_channels, "encrypt_secret", lambda value: "ciphertext")

    await youtube_channels.upsert_owned_channel(
        owner_telegram_user_id=111,
        external_channel_id="UC123",
        title="Alice Channel",
        refresh_token="plain-refresh-token",
        scopes=["youtube.upload"],
    )

    assert "plain-refresh-token" not in fetchrow.await_args.args
    assert "ciphertext" in fetchrow.await_args.args
