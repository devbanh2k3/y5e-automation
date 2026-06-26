"""Analytics agent — fetches YouTube performance data and applies feedback rules.

Collects view counts, likes, and comments from YouTube Data API v3,
stores metrics in the ``analytics`` table, flags underperforming videos,
and generates a daily summary report sent via Telegram.

Note:
    CTR (click-through rate) and audience retention require the YouTube
    Analytics API with YouTube CMS scope, which is only available to
    channels enrolled in the YouTube Partner Program.  For MVP, CTR and
    retention are stored from the analytics table's previous values or
    set to ``None`` when unavailable.  The feedback rules still fire if
    these values are populated externally (e.g. via a manual import or
    future Analytics API integration).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from agents.base_agent import BaseAgent
from core.config import get_settings
from core import database as db

logger = logging.getLogger(__name__)

_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# Maximum number of video IDs per API call (YouTube allows up to 50)
_MAX_IDS_PER_REQUEST = 50

# ── Feedback thresholds ──────────────────────────────────────
_MIN_CTR_PERCENT = 4.0
_MIN_RETENTION_PERCENT = 35.0


class AnalyticsError(Exception):
    """Raised when analytics data collection or processing fails."""


class AnalyticsAgent(BaseAgent):
    """Collects YouTube analytics and applies automated feedback rules.

    Workflow:
        1. Fetch all videos published in the last 30 days that have a
           ``youtube_id``.
        2. Batch-query the YouTube Data API for statistics.
        3. Upsert metrics into the ``analytics`` table.
        4. Apply feedback rules (low CTR → flag thumbnail, low retention
           → alert).
        5. Generate and send a daily summary report.
    """

    def __init__(self) -> None:
        super().__init__(name="analytics_agent")

    # ── Public entry point ───────────────────────────────────

    async def run(self) -> dict[str, Any]:
        """Collect analytics for recent videos and generate a daily report.

        Returns:
            A summary dict with ``total_videos``, ``total_views``,
            ``avg_ctr``, ``best_performer``, ``worst_performer``,
            and the full ``details`` list.

        Raises:
            AnalyticsError: If the YouTube API is unreachable or returns
                an unrecoverable error.
        """
        await self.log(None, "running")

        try:
            # ── Step 1: Fetch videos published in last 30 days ─
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            videos = await db.fetch(
                """
                SELECT v.id, v.topic_id, v.youtube_id, v.published_at,
                       t.title AS topic_title, t.category
                FROM videos v
                JOIN topics t ON t.id = v.topic_id
                WHERE v.youtube_id IS NOT NULL
                  AND v.published_at >= $1
                ORDER BY v.published_at DESC
                """,
                cutoff,
            )

            if not videos:
                self.logger.info("No published videos in the last 30 days.")
                report = self._empty_report()
                await self.notify("📊 Báo cáo ngày: Không có video nào trong 30 ngày qua.")
                await self.log(None, "completed")
                return report

            # ── Step 2: Batch-fetch stats from YouTube ─────────
            youtube_ids = [v["youtube_id"] for v in videos]
            stats_map = await self._fetch_youtube_stats(youtube_ids)

            # ── Step 3: Store analytics & apply rules ──────────
            analytics_data: list[dict[str, Any]] = []

            for video in videos:
                yt_id = video["youtube_id"]
                stats = stats_map.get(yt_id)

                if stats is None:
                    self.logger.warning(
                        "No stats returned for youtube_id=%s (video %d), skipping",
                        yt_id, video["id"],
                    )
                    continue

                view_count = int(stats.get("viewCount", 0))
                like_count = int(stats.get("likeCount", 0))
                comment_count = int(stats.get("commentCount", 0))

                # Retrieve previous analytics for CTR and retention
                # (these require the YouTube Analytics API — see module docstring)
                prev_analytics = await db.fetchrow(
                    """
                    SELECT ctr, avg_retention, watch_time_hr, subs_gained
                    FROM analytics
                    WHERE video_id = $1
                    ORDER BY recorded_at DESC LIMIT 1
                    """,
                    video["id"],
                )

                ctr = float(prev_analytics["ctr"]) if prev_analytics and prev_analytics["ctr"] else None
                avg_retention = (
                    float(prev_analytics["avg_retention"])
                    if prev_analytics and prev_analytics["avg_retention"]
                    else None
                )
                watch_time_hr = (
                    float(prev_analytics["watch_time_hr"])
                    if prev_analytics and prev_analytics["watch_time_hr"]
                    else 0.0
                )
                subs_gained = (
                    int(prev_analytics["subs_gained"])
                    if prev_analytics and prev_analytics["subs_gained"]
                    else 0
                )

                # Insert new analytics row
                now = datetime.now(timezone.utc)
                await db.execute(
                    """
                    INSERT INTO analytics
                        (video_id, views, ctr, avg_retention, watch_time_hr,
                         subs_gained, recorded_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    video["id"],
                    view_count,
                    ctr or 0.0,
                    avg_retention or 0.0,
                    watch_time_hr,
                    subs_gained,
                    now,
                )

                entry: dict[str, Any] = {
                    "video_id": video["id"],
                    "youtube_id": yt_id,
                    "title": video["topic_title"],
                    "category": video["category"],
                    "views": view_count,
                    "likes": like_count,
                    "comments": comment_count,
                    "ctr": ctr,
                    "avg_retention": avg_retention,
                    "watch_time_hr": watch_time_hr,
                    "subs_gained": subs_gained,
                }
                analytics_data.append(entry)

                # ── Step 4: Apply feedback rules ───────────────
                await self._apply_feedback_rules(
                    video_id=video["id"],
                    title=video["topic_title"],
                    ctr=ctr,
                    avg_retention=avg_retention,
                )

            # ── Step 5: Generate daily report ──────────────────
            report = self._build_report(analytics_data)
            await self._send_daily_report(report)

            await self.log(None, "completed")
            return report

        except Exception as exc:
            error_msg = f"Analytics collection failed: {exc}"
            self.logger.error(error_msg, exc_info=True)
            await self.log(None, "failed", error=str(exc)[:500])
            await self.notify(f"❌ Analytics failed: {exc}")
            raise AnalyticsError(error_msg) from exc

    # ── YouTube Data API ─────────────────────────────────────

    async def _fetch_youtube_stats(
        self, youtube_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch video statistics from the YouTube Data API in batches.

        Args:
            youtube_ids: List of YouTube video IDs.

        Returns:
            A mapping of ``{youtube_id: statistics_dict}``.
        """
        settings = get_settings()
        api_key = settings.youtube_api_key

        if not api_key:
            self.logger.warning(
                "YOUTUBE_API_KEY not configured. Returning empty stats."
            )
            return {}

        stats_map: dict[str, dict[str, Any]] = {}

        # Process in batches of 50 (YouTube API limit)
        for batch_start in range(0, len(youtube_ids), _MAX_IDS_PER_REQUEST):
            batch = youtube_ids[batch_start : batch_start + _MAX_IDS_PER_REQUEST]
            ids_param = ",".join(batch)

            params = {
                "part": "statistics,snippet",
                "id": ids_param,
                "key": api_key,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(_YT_VIDEOS_URL, params=params)

                if resp.status_code == 403:
                    self.logger.error(
                        "YouTube API quota exceeded or forbidden: %s",
                        resp.text[:500],
                    )
                    raise AnalyticsError(
                        f"YouTube API quota exceeded (HTTP 403): {resp.text[:300]}"
                    )

                if resp.status_code != 200:
                    self.logger.error(
                        "YouTube API error (HTTP %d): %s",
                        resp.status_code, resp.text[:500],
                    )
                    continue  # Skip this batch, proceed with others

                data = resp.json()

            for item in data.get("items", []):
                vid_id = item.get("id", "")
                statistics = item.get("statistics", {})
                stats_map[vid_id] = statistics

            self.logger.info(
                "Fetched stats for batch of %d videos (%d results)",
                len(batch), len(data.get("items", [])),
            )

        return stats_map

    # ── Feedback rules ───────────────────────────────────────

    async def _apply_feedback_rules(
        self,
        video_id: int,
        title: str,
        ctr: float | None,
        avg_retention: float | None,
    ) -> None:
        """Apply automated feedback rules based on performance metrics.

        Args:
            video_id: Database video ID.
            title: Video title (for notifications).
            ctr: Click-through rate percentage (``None`` if unavailable).
            avg_retention: Average view retention percentage
                (``None`` if unavailable).
        """
        if ctr is not None and ctr > 0 and ctr < _MIN_CTR_PERCENT:
            await self.notify(
                f"⚠️ Video '<b>{title}</b>' CTR thấp ({ctr:.1f}%). "
                f"Cần thumbnail mới."
            )
            await db.execute(
                "UPDATE videos SET status = 'needs_thumbnail' WHERE id = $1",
                video_id,
            )
            self.logger.info(
                "Video %d flagged for thumbnail regeneration (CTR=%.1f%%)",
                video_id, ctr,
            )

        if avg_retention is not None and avg_retention > 0 and avg_retention < _MIN_RETENTION_PERCENT:
            await self.notify(
                f"⚠️ Video '<b>{title}</b>' retention thấp ({avg_retention:.1f}%). "
                f"Cần cải thiện hook intro."
            )
            self.logger.info(
                "Video %d has low retention (%.1f%%), notified for hook improvement",
                video_id, avg_retention,
            )

    # ── Report generation ────────────────────────────────────

    @staticmethod
    def _build_report(analytics_data: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a summary report from collected analytics data.

        Args:
            analytics_data: List of per-video analytics dicts.

        Returns:
            A summary dict with aggregate statistics.
        """
        if not analytics_data:
            return AnalyticsAgent._empty_report()

        total_views = sum(v["views"] for v in analytics_data)
        total_likes = sum(v["likes"] for v in analytics_data)
        total_comments = sum(v["comments"] for v in analytics_data)
        total_subs = sum(v.get("subs_gained", 0) or 0 for v in analytics_data)

        # Calculate average CTR from available data
        ctr_values = [v["ctr"] for v in analytics_data if v["ctr"] is not None and v["ctr"] > 0]
        avg_ctr = sum(ctr_values) / len(ctr_values) if ctr_values else None

        # Find best and worst performers by views
        sorted_by_views = sorted(analytics_data, key=lambda x: x["views"], reverse=True)
        best_performer = sorted_by_views[0]["title"] if sorted_by_views else "N/A"
        best_views = sorted_by_views[0]["views"] if sorted_by_views else 0
        worst_performer = sorted_by_views[-1]["title"] if sorted_by_views else "N/A"
        worst_views = sorted_by_views[-1]["views"] if sorted_by_views else 0

        return {
            "total_videos": len(analytics_data),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_subs_gained": total_subs,
            "avg_ctr": avg_ctr,
            "best_performer": best_performer,
            "best_views": best_views,
            "worst_performer": worst_performer,
            "worst_views": worst_views,
            "details": analytics_data,
        }

    @staticmethod
    def _empty_report() -> dict[str, Any]:
        """Return an empty report structure.

        Returns:
            A report dict with all counters set to zero.
        """
        return {
            "total_videos": 0,
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
            "total_subs_gained": 0,
            "avg_ctr": None,
            "best_performer": "N/A",
            "best_views": 0,
            "worst_performer": "N/A",
            "worst_views": 0,
            "details": [],
        }

    async def _send_daily_report(self, report: dict[str, Any]) -> None:
        """Send the daily analytics report via Telegram.

        Args:
            report: The summary report dict.
        """
        avg_ctr_str = f"{report['avg_ctr']:.1f}%" if report["avg_ctr"] is not None else "N/A"

        message = (
            f"📊 <b>Báo cáo ngày</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 Videos: <b>{report['total_videos']}</b>\n"
            f"👀 Views: <b>{report['total_views']:,}</b>\n"
            f"👍 Likes: <b>{report['total_likes']:,}</b>\n"
            f"💬 Comments: <b>{report['total_comments']:,}</b>\n"
            f"👥 Subs gained: <b>{report['total_subs_gained']:,}</b>\n"
            f"📈 Avg CTR: <b>{avg_ctr_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Best: <b>{report['best_performer']}</b> ({report['best_views']:,} views)\n"
            f"📉 Worst: <b>{report['worst_performer']}</b> ({report['worst_views']:,} views)"
        )

        await self.notify(message)
        self.logger.info(
            "Daily report sent: %d videos, %d total views",
            report["total_videos"], report["total_views"],
        )
