"""Tenant-scoped YouTube channel and OAuth state persistence."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Literal

from core.database import execute, fetch, fetchrow
from core.token_crypto import encrypt_secret

OAuthPurpose = Literal["connect_ticket", "oauth_state"]


class ChannelAccessError(PermissionError):
    """Raised when a channel is not owned and active for the requester."""


class OAuthStateError(ValueError):
    """Raised when an OAuth token is invalid, expired, or already consumed."""


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def issue_oauth_token(
    *,
    owner_telegram_user_id: int,
    purpose: OAuthPurpose,
    ttl_seconds: int = 600,
) -> str:
    """Create a short-lived one-time token while storing only its hash."""
    raw_token = secrets.token_urlsafe(32)
    await execute(
        """
        INSERT INTO youtube_oauth_states (
            state_hash, owner_telegram_user_id, purpose, expires_at
        )
        VALUES ($1, $2, $3, NOW() + ($4 * INTERVAL '1 second'))
        """,
        _token_hash(raw_token),
        owner_telegram_user_id,
        purpose,
        max(1, ttl_seconds),
    )
    return raw_token


async def consume_oauth_token(raw_token: str, *, purpose: OAuthPurpose) -> int:
    """Atomically consume a valid one-time token and return its owner."""
    row = await fetchrow(
        """
        UPDATE youtube_oauth_states
        SET consumed_at = NOW()
        WHERE state_hash = $1
          AND purpose = $2
          AND consumed_at IS NULL
          AND expires_at > NOW()
        RETURNING owner_telegram_user_id
        """,
        _token_hash(raw_token),
        purpose,
    )
    if not row:
        raise OAuthStateError("OAuth link is invalid, expired, or already used")
    return int(row["owner_telegram_user_id"])


async def list_owned_channels(owner_telegram_user_id: int) -> list[dict[str, Any]]:
    """List channels visible to one Telegram user."""
    return await fetch(
        """
        SELECT youtube_channel_id::text, external_channel_id, title, status,
               last_refreshed_at, created_at, updated_at
        FROM youtube_channels
        WHERE owner_telegram_user_id = $1
        ORDER BY title, created_at
        """,
        owner_telegram_user_id,
    )


async def get_owned_channel(
    channel_id: str,
    *,
    owner_telegram_user_id: int,
    require_active: bool = False,
) -> dict[str, Any]:
    """Return a channel only when it belongs to the requesting user."""
    status_clause = "AND status = 'active'" if require_active else ""
    row = await fetchrow(
        f"""
        SELECT youtube_channel_id::text, owner_telegram_user_id,
               external_channel_id, title, encrypted_refresh_token, scopes,
               status, last_refreshed_at
        FROM youtube_channels
        WHERE youtube_channel_id = $1::uuid
          AND owner_telegram_user_id = $2
          {status_clause}
        """,
        channel_id,
        owner_telegram_user_id,
    )
    if not row:
        raise ChannelAccessError("YouTube channel is unavailable")
    return row


async def upsert_owned_channel(
    *,
    owner_telegram_user_id: int,
    external_channel_id: str,
    title: str,
    refresh_token: str,
    scopes: list[str],
) -> dict[str, Any]:
    """Create or reconnect one channel under its initiating Telegram user."""
    encrypted_refresh_token = encrypt_secret(refresh_token)
    row = await fetchrow(
        """
        INSERT INTO youtube_channels (
            owner_telegram_user_id, external_channel_id, title,
            encrypted_refresh_token, scopes, status, last_refreshed_at
        )
        VALUES ($1, $2, $3, $4, $5, 'active', NOW())
        ON CONFLICT (owner_telegram_user_id, external_channel_id)
        DO UPDATE SET
            title = EXCLUDED.title,
            encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
            scopes = EXCLUDED.scopes,
            status = 'active',
            last_refreshed_at = NOW(),
            updated_at = NOW()
        RETURNING youtube_channel_id::text, external_channel_id, title, status
        """,
        owner_telegram_user_id,
        external_channel_id,
        title,
        encrypted_refresh_token,
        scopes,
    )
    if not row:
        raise RuntimeError("YouTube channel could not be saved")
    return row


async def select_owned_channel(*, owner_telegram_user_id: int, channel_id: str) -> dict[str, Any]:
    """Store an active owned channel as the user's next batch destination."""
    channel = await get_owned_channel(
        channel_id,
        owner_telegram_user_id=owner_telegram_user_id,
        require_active=True,
    )
    await execute(
        """
        UPDATE telegram_users
        SET selected_youtube_channel_id = $2::uuid, updated_at = NOW()
        WHERE telegram_user_id = $1 AND is_active = TRUE
        """,
        owner_telegram_user_id,
        channel_id,
    )
    return channel


async def get_selected_channel(owner_telegram_user_id: int) -> dict[str, Any] | None:
    """Return the currently selected active channel for one user."""
    return await fetchrow(
        """
        SELECT c.youtube_channel_id::text, c.external_channel_id, c.title, c.status
        FROM telegram_users u
        JOIN youtube_channels c
          ON c.youtube_channel_id = u.selected_youtube_channel_id
        WHERE u.telegram_user_id = $1
          AND u.is_active = TRUE
          AND c.owner_telegram_user_id = u.telegram_user_id
          AND c.status = 'active'
        """,
        owner_telegram_user_id,
    )


async def consume_selected_channel(owner_telegram_user_id: int) -> dict[str, Any] | None:
    """Atomically consume the channel selected for the user's next batch."""
    return await fetchrow(
        """
        WITH selected AS (
            UPDATE telegram_users
            SET selected_youtube_channel_id = NULL, updated_at = NOW()
            WHERE telegram_user_id = $1
              AND is_active = TRUE
              AND selected_youtube_channel_id IS NOT NULL
            RETURNING selected_youtube_channel_id
        )
        SELECT c.youtube_channel_id::text, c.external_channel_id, c.title, c.status
        FROM selected s
        JOIN youtube_channels c ON c.youtube_channel_id = s.selected_youtube_channel_id
        WHERE c.owner_telegram_user_id = $1 AND c.status = 'active'
        """,
        owner_telegram_user_id,
    )


async def mark_auth_required(*, owner_telegram_user_id: int, channel_id: str) -> None:
    """Disable uploads for an owned channel until OAuth is renewed."""
    result = await execute(
        """
        UPDATE youtube_channels
        SET status = 'auth_required', updated_at = NOW()
        WHERE youtube_channel_id = $1::uuid AND owner_telegram_user_id = $2
        """,
        channel_id,
        owner_telegram_user_id,
    )
    if result.endswith(" 0"):
        raise ChannelAccessError("YouTube channel is unavailable")


async def disconnect_owned_channel(*, owner_telegram_user_id: int, channel_id: str) -> None:
    """Erase the stored credential and disconnect an owned channel."""
    result = await execute(
        """
        UPDATE youtube_channels
        SET status = 'disconnected', encrypted_refresh_token = '', updated_at = NOW()
        WHERE youtube_channel_id = $1::uuid AND owner_telegram_user_id = $2
        """,
        channel_id,
        owner_telegram_user_id,
    )
    if result.endswith(" 0"):
        raise ChannelAccessError("YouTube channel is unavailable")
