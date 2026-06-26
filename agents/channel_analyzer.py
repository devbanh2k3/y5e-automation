"""Channel analysis agent — fetches YouTube channel data and generates insights."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings

logger = logging.getLogger(__name__)

# YouTube Data API v3 base URL
_YT_API = "https://www.googleapis.com/youtube/v3"

# ISO 8601 duration → seconds conversion pattern
_ISO_DURATION_RE = re.compile(
    r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def _parse_channel_url(url: str) -> tuple[str, str]:
    """Extract the channel identifier and its type from a YouTube URL.

    Supports:
        - youtube.com/@handle      → ("handle",  "@handle")
        - youtube.com/channel/ID   → ("id",      "UCxxxx")
        - youtube.com/c/name       → ("custom",  "name")

    Args:
        url: A YouTube channel URL.

    Returns:
        A ``(identifier_type, identifier_value)`` tuple.

    Raises:
        ValueError: If the URL format is not recognised.
    """
    url = url.strip().rstrip("/")

    # @handle format
    match = re.search(r"youtube\.com/@([\w\-\.]+)", url)
    if match:
        return "handle", f"@{match.group(1)}"

    # /channel/UCXXXX format
    match = re.search(r"youtube\.com/channel/(UC[\w\-]+)", url)
    if match:
        return "id", match.group(1)

    # /c/customname format
    match = re.search(r"youtube\.com/c/([\w\-]+)", url)
    if match:
        return "custom", match.group(1)

    raise ValueError(
        f"Unsupported YouTube channel URL format: {url}. "
        "Expected youtube.com/@handle, youtube.com/channel/ID, or youtube.com/c/name"
    )


def _iso_duration_to_seconds(duration: str) -> int:
    """Convert an ISO 8601 duration string (e.g. ``PT12M34S``) to seconds.

    Args:
        duration: ISO 8601 duration from YouTube API.

    Returns:
        Total duration in seconds.
    """
    match = _ISO_DURATION_RE.match(duration)
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


class ChannelAnalyzer(BaseAgent):
    """Analyse a YouTube channel's content and performance patterns.

    Fetches channel metadata, recent video details, and transcripts, then
    uses AI to identify patterns in categories, titles, style, and scheduling.
    """

    def __init__(self) -> None:
        super().__init__(name="channel_analyzer")

    async def run(self, channel_url: str) -> dict[str, Any]:
        """Analyse a YouTube channel and store insights.

        Args:
            channel_url: Full URL to the YouTube channel.

        Returns:
            A dict containing the full AI analysis plus channel metadata.
        """
        await self.log(topic_id=None, status="running")

        try:
            settings = get_settings()
            api_key = settings.youtube_api_key

            # ── Step 1: Resolve channel identifier ──────────────
            id_type, id_value = _parse_channel_url(channel_url)
            self.logger.info("Parsed channel URL → type=%s, value=%s", id_type, id_value)

            # ── Step 2: Fetch channel info ──────────────────────
            channel_info = await self._fetch_channel_info(api_key, id_type, id_value)
            channel_id = channel_info["id"]
            channel_name = channel_info["snippet"]["title"]
            subscriber_count = int(
                channel_info.get("statistics", {}).get("subscriberCount", 0)
            )
            video_count = int(
                channel_info.get("statistics", {}).get("videoCount", 0)
            )
            uploads_playlist_id = (
                channel_info["contentDetails"]["relatedPlaylists"]["uploads"]
            )

            self.logger.info(
                "Channel: %s (subs=%d, videos=%d, uploads_pl=%s)",
                channel_name, subscriber_count, video_count, uploads_playlist_id,
            )

            # ── Step 3: Fetch recent video IDs ──────────────────
            video_ids = await self._fetch_playlist_video_ids(
                api_key, uploads_playlist_id, max_results=50
            )
            self.logger.info("Fetched %d video IDs from uploads playlist", len(video_ids))

            # ── Step 4: Fetch video details ─────────────────────
            videos = await self._fetch_video_details(api_key, video_ids)
            self.logger.info("Fetched details for %d videos", len(videos))

            # ── Step 5: Fetch transcripts for top 10 videos ─────
            sorted_videos = sorted(
                videos, key=lambda v: int(v.get("statistics", {}).get("viewCount", 0)),
                reverse=True,
            )
            top_videos = sorted_videos[:10]
            transcripts = await self._fetch_transcripts(
                [v["id"] for v in top_videos]
            )
            self.logger.info(
                "Fetched transcripts for %d / %d top videos",
                sum(1 for t in transcripts.values() if t), len(top_videos),
            )

            # ── Step 6: Store reference channel & videos in DB ──
            db_channel_id = await self._upsert_reference_channel(
                channel_url=channel_url,
                channel_name=channel_name,
                channel_id=channel_id,
                subscriber_count=subscriber_count,
                video_count=video_count,
            )
            await self._store_reference_videos(db_channel_id, videos, transcripts)

            # ── Step 7: AI analysis ─────────────────────────────
            analysis = await self._ai_analyse(
                channel_name=channel_name,
                videos=videos,
                transcripts=transcripts,
            )

            # ── Step 8: Update channel record with analysis ─────
            await db.execute(
                """
                UPDATE reference_channels
                SET top_categories  = $1,
                    title_patterns  = $2,
                    content_style   = $3,
                    thumbnail_style = $4,
                    optimal_length  = $5,
                    posting_schedule = $6,
                    tag_strategy    = $7,
                    topic_gaps      = $8,
                    last_analyzed_at = $9
                WHERE id = $10
                """,
                json.dumps(analysis.get("top_categories", [])),
                json.dumps(analysis.get("title_patterns", [])),
                analysis.get("content_style", ""),
                analysis.get("thumbnail_style", ""),
                json.dumps(analysis.get("optimal_length", {})),
                json.dumps(analysis.get("posting_schedule", {})),
                json.dumps(analysis.get("tag_strategy", [])),
                json.dumps(analysis.get("topic_gaps", [])),
                datetime.now(timezone.utc),
                db_channel_id,
            )

            await self.log(topic_id=None, status="completed")
            await self.notify(
                f"Channel analysis complete for <b>{channel_name}</b> "
                f"({subscriber_count:,} subs, {len(videos)} videos analysed)"
            )

            return {
                "channel_id": db_channel_id,
                "channel_name": channel_name,
                "subscriber_count": subscriber_count,
                "video_count": video_count,
                "videos_analysed": len(videos),
                "transcripts_fetched": sum(1 for t in transcripts.values() if t),
                **analysis,
            }

        except Exception as exc:
            await self.log(topic_id=None, status="failed", error=str(exc))
            await self.notify(f"❌ Channel analysis failed: {exc}")
            raise

    # ── YouTube Data API helpers ──────────────────────────────

    async def _fetch_channel_info(
        self, api_key: str, id_type: str, id_value: str,
    ) -> dict[str, Any]:
        """Fetch channel info via channels.list endpoint.

        Args:
            api_key: YouTube Data API key.
            id_type: One of ``"handle"``, ``"id"``, ``"custom"``.
            id_value: The channel identifier.

        Returns:
            The channel resource dict.

        Raises:
            ValueError: If the channel cannot be found.
        """
        params: dict[str, str] = {
            "part": "snippet,statistics,contentDetails",
            "key": api_key,
        }

        if id_type == "handle":
            params["forHandle"] = id_value
        elif id_type == "id":
            params["id"] = id_value
        elif id_type == "custom":
            # Custom URLs require a search first, then resolve by ID
            params["forHandle"] = f"@{id_value}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{_YT_API}/channels", params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            raise ValueError(
                f"No channel found for {id_type}={id_value}. "
                "Check the URL and ensure the channel exists."
            )
        return items[0]

    async def _fetch_playlist_video_ids(
        self, api_key: str, playlist_id: str, max_results: int = 50,
    ) -> list[str]:
        """Fetch video IDs from a playlist (typically the uploads playlist).

        Args:
            api_key: YouTube Data API key.
            playlist_id: The playlist ID.
            max_results: Maximum number of video IDs to return (capped at 50).

        Returns:
            A list of YouTube video IDs.
        """
        video_ids: list[str] = []
        page_token: str | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(video_ids) < max_results:
                params: dict[str, str | int] = {
                    "part": "contentDetails",
                    "playlistId": playlist_id,
                    "maxResults": min(50, max_results - len(video_ids)),
                    "key": api_key,
                }
                if page_token:
                    params["pageToken"] = page_token

                resp = await client.get(f"{_YT_API}/playlistItems", params=params)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("items", []):
                    vid = item["contentDetails"]["videoId"]
                    video_ids.append(vid)

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        return video_ids[:max_results]

    async def _fetch_video_details(
        self, api_key: str, video_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch full details for a batch of video IDs.

        The YouTube API accepts up to 50 IDs per request, so this handles
        batching transparently.

        Args:
            api_key: YouTube Data API key.
            video_ids: List of YouTube video IDs.

        Returns:
            A list of video resource dicts.
        """
        all_videos: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                params: dict[str, str] = {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "key": api_key,
                }
                resp = await client.get(f"{_YT_API}/videos", params=params)
                resp.raise_for_status()
                data = resp.json()
                all_videos.extend(data.get("items", []))

        return all_videos

    async def _fetch_transcripts(
        self, video_ids: list[str],
    ) -> dict[str, str | None]:
        """Attempt to fetch transcripts for a list of video IDs.

        Uses ``youtube_transcript_api`` with fallback language order:
        Vietnamese → Japanese → English.

        Args:
            video_ids: Video IDs to fetch transcripts for.

        Returns:
            A dict mapping video_id → transcript_text (or ``None`` on failure).
        """
        transcripts: dict[str, str | None] = {}

        for vid in video_ids:
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(
                    vid, languages=["vi", "ja", "en"]
                )
                transcripts[vid] = " ".join(t["text"] for t in transcript_list)
            except Exception as exc:
                self.logger.debug("Transcript unavailable for %s: %s", vid, exc)
                transcripts[vid] = None

        return transcripts

    # ── Database persistence ──────────────────────────────────

    async def _upsert_reference_channel(
        self,
        channel_url: str,
        channel_name: str,
        channel_id: str,
        subscriber_count: int,
        video_count: int,
    ) -> int:
        """Insert or update the reference_channels record.

        Args:
            channel_url: Original URL provided by the user.
            channel_name: Human-readable channel title.
            channel_id: YouTube channel ID (UC...).
            subscriber_count: Current subscriber count.
            video_count: Total number of videos on the channel.

        Returns:
            The database row ID for the channel.
        """
        existing = await db.fetchrow(
            "SELECT id FROM reference_channels WHERE channel_url = $1",
            channel_url,
        )

        if existing:
            await db.execute(
                """
                UPDATE reference_channels
                SET channel_name = $1, channel_id = $2,
                    subscriber_count = $3, video_count = $4
                WHERE id = $5
                """,
                channel_name, channel_id, subscriber_count, video_count,
                existing["id"],
            )
            return existing["id"]

        row = await db.fetchrow(
            """
            INSERT INTO reference_channels
                (channel_url, channel_name, channel_id, subscriber_count, video_count, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            channel_url, channel_name, channel_id,
            subscriber_count, video_count, datetime.now(timezone.utc),
        )
        return row["id"]  # type: ignore[index]

    async def _store_reference_videos(
        self,
        db_channel_id: int,
        videos: list[dict[str, Any]],
        transcripts: dict[str, str | None],
    ) -> None:
        """Insert or update reference_videos rows for all fetched videos.

        Args:
            db_channel_id: The reference_channels.id foreign key.
            videos: List of video resource dicts from YouTube API.
            transcripts: Mapping of video_id → transcript text.
        """
        for video in videos:
            vid = video["id"]
            snippet = video.get("snippet", {})
            stats = video.get("statistics", {})
            content = video.get("contentDetails", {})

            published_raw = snippet.get("publishedAt")
            published_at: datetime | None = None
            if published_raw:
                published_at = datetime.fromisoformat(
                    published_raw.replace("Z", "+00:00")
                )

            duration_sec = _iso_duration_to_seconds(content.get("duration", "PT0S"))
            tags = snippet.get("tags", [])
            transcript_text = transcripts.get(vid, "") or ""

            existing = await db.fetchrow(
                "SELECT id FROM reference_videos WHERE youtube_video_id = $1", vid
            )

            if existing:
                await db.execute(
                    """
                    UPDATE reference_videos
                    SET title = $1, views = $2, likes = $3, comments = $4,
                        duration_sec = $5, published_at = $6, description = $7,
                        tags = $8, thumbnail_url = $9, transcript = $10
                    WHERE id = $11
                    """,
                    snippet.get("title", ""),
                    int(stats.get("viewCount", 0)),
                    int(stats.get("likeCount", 0)),
                    int(stats.get("commentCount", 0)),
                    duration_sec,
                    published_at,
                    snippet.get("description", "")[:2000],
                    json.dumps(tags),
                    snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                    transcript_text[:10000],
                    existing["id"],
                )
            else:
                await db.execute(
                    """
                    INSERT INTO reference_videos
                        (channel_id, youtube_video_id, title, views, likes, comments,
                         duration_sec, published_at, description, tags, thumbnail_url,
                         transcript, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    """,
                    db_channel_id,
                    vid,
                    snippet.get("title", ""),
                    int(stats.get("viewCount", 0)),
                    int(stats.get("likeCount", 0)),
                    int(stats.get("commentCount", 0)),
                    duration_sec,
                    published_at,
                    snippet.get("description", "")[:2000],
                    json.dumps(tags),
                    snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                    transcript_text[:10000],
                    datetime.now(timezone.utc),
                )

    # ── AI analysis ───────────────────────────────────────────

    async def _ai_analyse(
        self,
        channel_name: str,
        videos: list[dict[str, Any]],
        transcripts: dict[str, str | None],
    ) -> dict[str, Any]:
        """Send all video data to AI for comprehensive channel analysis.

        Args:
            channel_name: Human-readable channel name.
            videos: Full video resource dicts from YouTube API.
            transcripts: Mapping of video_id → transcript text.

        Returns:
            A dict containing the structured analysis results.
        """
        # Build a compact representation for each video
        video_summaries: list[dict[str, Any]] = []
        for v in videos:
            snippet = v.get("snippet", {})
            stats = v.get("statistics", {})
            content = v.get("contentDetails", {})
            vid = v["id"]

            summary: dict[str, Any] = {
                "title": snippet.get("title", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration": content.get("duration", ""),
                "tags": snippet.get("tags", [])[:15],
                "published": snippet.get("publishedAt", ""),
            }

            # Include transcript snippet for top videos
            transcript_text = transcripts.get(vid)
            if transcript_text:
                summary["transcript_excerpt"] = transcript_text[:1500]

            video_summaries.append(summary)

        prompt = f"""Analyze these {len(video_summaries)} videos from YouTube channel "{channel_name}" and return JSON with:
- top_categories: [{{category, avg_views, count}}] — categorize each video into: WhatIf, Timeline, Ranking, Comparison, History, Science, Geography, Evolution, Other
- title_patterns: [string] — identify 3-5 successful title templates
- content_style: string — describe writing style, tone, hooks used
- thumbnail_style: string — describe visual patterns
- optimal_length: {{category: "X-Y min"}} — best duration per category
- posting_schedule: {{best_days: [string], best_time: string}}
- tag_strategy: [string] — most common tags on high-view videos
- topic_gaps: [string] — 10 topics this channel hasn't covered but should

Video data:
{json.dumps(video_summaries, ensure_ascii=False, default=str)[:12000]}
"""

        system_prompt = (
            "You are a YouTube analytics expert. Analyse the provided video data "
            "and return structured insights in valid JSON format. Be specific with "
            "numbers and patterns. Every category classification must be one of: "
            "WhatIf, Timeline, Ranking, Comparison, History, Science, Geography, "
            "Evolution, Other."
        )

        analysis = await self.ai_json(prompt, system=system_prompt)
        self.logger.info("AI analysis complete — %d categories identified", len(analysis.get("top_categories", [])))
        return analysis
