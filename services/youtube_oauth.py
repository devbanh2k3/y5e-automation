"""Server-side Google OAuth flow for tenant-owned YouTube channels."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from core import youtube_channels
from core.config import get_settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)


class YouTubeOAuthError(RuntimeError):
    """Raised for sanitized OAuth or channel identity failures."""


def callback_uri() -> str:
    settings = get_settings()
    return f"{settings.public_base_url.rstrip('/')}{settings.youtube_oauth_callback_path}"


def build_authorization_url(*, state: str, redirect_uri: str) -> str:
    """Build an offline Google consent URL with minimum YouTube scopes."""
    params = {
        "client_id": get_settings().youtube_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def start_oauth(connect_ticket: str) -> str:
    """Consume a Telegram connect ticket and return the Google consent URL."""
    owner_id = await youtube_channels.consume_oauth_token(
        connect_ticket,
        purpose="connect_ticket",
    )
    state = await youtube_channels.issue_oauth_token(
        owner_telegram_user_id=owner_id,
        purpose="oauth_state",
    )
    return build_authorization_url(state=state, redirect_uri=callback_uri())


async def exchange_authorization_code(code: str) -> dict[str, Any]:
    """Exchange an authorization code without exposing provider error bodies."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.youtube_oauth_client_id,
                "client_secret": settings.youtube_oauth_client_secret,
                "redirect_uri": callback_uri(),
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise YouTubeOAuthError("Google authorization code exchange failed")
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise YouTubeOAuthError("Google authorization response is incomplete")
    return payload


async def fetch_authenticated_channel(access_token: str) -> dict[str, str]:
    """Resolve the exact channel identity selected by the Google account."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            YOUTUBE_CHANNELS_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        raise YouTubeOAuthError("YouTube channel identity lookup failed")
    items = response.json().get("items") or []
    if len(items) != 1:
        raise YouTubeOAuthError("Google account must resolve to one YouTube channel")
    item = items[0]
    external_channel_id = str(item.get("id") or "").strip()
    title = str((item.get("snippet") or {}).get("title") or "").strip()
    if not external_channel_id or not title:
        raise YouTubeOAuthError("YouTube channel identity is incomplete")
    return {"external_channel_id": external_channel_id, "title": title}


async def complete_oauth(*, code: str, state: str) -> dict[str, Any]:
    """Consume OAuth state and persist the verified tenant-owned channel."""
    owner_id = await youtube_channels.consume_oauth_token(state, purpose="oauth_state")
    tokens = await exchange_authorization_code(code)
    refresh_token = str(tokens.get("refresh_token") or "")
    if not refresh_token:
        raise YouTubeOAuthError(
            "Google did not return a refresh token; reconnect and grant consent"
        )
    identity = await fetch_authenticated_channel(str(tokens["access_token"]))
    scopes = str(tokens.get("scope") or "").split()
    channel = await youtube_channels.upsert_owned_channel(
        owner_telegram_user_id=owner_id,
        external_channel_id=identity["external_channel_id"],
        title=identity["title"],
        refresh_token=refresh_token,
        scopes=scopes,
    )
    return {"owner_telegram_user_id": owner_id, **channel}
