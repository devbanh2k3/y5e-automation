"""Telegram callback handlers for review approval and rejection."""

from __future__ import annotations

from typing import Any

from core import production_tasks, youtube_channels, youtube_upload_jobs
from core.reviews import reject_review
from services.telegram_channels import TelegramResponse


async def handle_review_callback(*, telegram_user_id: int, data: str) -> str | TelegramResponse:
    """Handle one Telegram inline review action."""
    user = await production_tasks.get_authorized_user(telegram_user_id)
    if not user:
        return "You are not authorized to review videos."

    parsed = parse_review_callback(data)
    if parsed is None:
        return "Unsupported review action."

    action, detail, review_id = parsed
    try:
        if action == "approve":
            return await _approval_channel_picker(
                telegram_user_id=telegram_user_id,
                review_id=review_id,
            )
        if action == "approve_channel":
            channel = await _channel_by_index(
                telegram_user_id=telegram_user_id,
                one_based_index=detail,
            )
            job = await youtube_upload_jobs.approve_and_enqueue(
                review_id=review_id,
                owner_telegram_user_id=telegram_user_id,
                youtube_channel_id=str(channel["youtube_channel_id"]),
            )
            return (
                "Đã approve video và đưa vào hàng chờ upload.\n"
                f"Kênh: {channel['title']}\n"
                f"Trạng thái: {str(job.get('status') or 'queued').replace('_', ' ')}"
            )
        await production_tasks.assert_review_owner(
            review_id=review_id,
            owner_telegram_user_id=telegram_user_id,
        )
        await reject_review(review_id, reason=detail, notes=f"rejected from Telegram: {detail}")
        await production_tasks.mark_task_review_decision(review_id=review_id, status="rejected")
        return f"Đã reject video.\nLý do: {_reject_reason_label(detail)}"
    except KeyError:
        return "Không tìm thấy video cần duyệt. Mở /reviews để xem danh sách mới nhất."
    except PermissionError:
        return "Review or YouTube channel is unavailable."
    except ValueError as exc:
        return str(exc)


async def _approval_channel_picker(*, telegram_user_id: int, review_id: str) -> TelegramResponse:
    channels = await youtube_channels.list_owned_channels(telegram_user_id)
    active_channels = [channel for channel in channels if channel.get("status") == "active"]
    if not active_channels:
        return TelegramResponse(
            "Chưa có kênh YouTube đang hoạt động. Mở /channels để kết nối kênh trước."
        )
    return TelegramResponse(
        "Chọn kênh YouTube để upload video này:",
        _build_review_channel_keyboard(review_id=review_id, channels=active_channels),
    )


def _build_review_channel_keyboard(*, review_id: str, channels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": str(channel["title"]),
                    "callback_data": f"rv:ch:{index}:{review_id}",
                }
            ]
            for index, channel in enumerate(channels, start=1)
        ]
    }


async def _channel_by_index(*, telegram_user_id: int, one_based_index: str) -> dict[str, Any]:
    try:
        index = int(one_based_index)
    except ValueError as exc:
        raise PermissionError("YouTube channel is unavailable") from exc
    if index < 1:
        raise PermissionError("YouTube channel is unavailable")
    channels = await youtube_channels.list_owned_channels(telegram_user_id)
    active_channels = [channel for channel in channels if channel.get("status") == "active"]
    if index > len(active_channels):
        raise PermissionError("YouTube channel is unavailable")
    return active_channels[index - 1]


def parse_review_callback(data: str) -> tuple[str, str, str] | None:
    """Parse compact Telegram callback data."""
    if data.startswith("rv:ok:"):
        return "approve", "", data.removeprefix("rv:ok:")
    if data.startswith("rv:ch:"):
        parts = data.split(":", 3)
        if len(parts) != 4:
            return None
        _, _, channel_index, review_id = parts
        if not review_id or not channel_index:
            return None
        return "approve_channel", channel_index, review_id
    if data.startswith("rv:rej:"):
        parts = data.split(":", 3)
        if len(parts) != 4:
            return None
        _, _, reason, review_id = parts
        if not reason or not review_id:
            return None
        return "reject", reason, review_id
    return None


def _reject_reason_label(reason: str) -> str:
    labels = {
        "wrong_image": "Ảnh sai hoặc chưa phù hợp",
        "bad_fact": "Dữ kiện chưa đúng",
        "bad_text": "Text chưa ổn",
        "bad_video": "Video/render lỗi",
        "bad_layout": "Bố cục chưa phù hợp",
        "bad_topic": "Topic chưa phù hợp",
        "bad_metric": "Metric chưa đúng",
        "other": "Lý do khác",
    }
    return labels.get(reason, reason)
