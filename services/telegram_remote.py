"""Telegram remote-control command handling for production tasks."""

from __future__ import annotations

from core import production_tasks, youtube_upload_jobs
from core.config import get_settings
from core.reviews import get_review
from services.telegram_channels import TelegramResponse, channel_list_response
from services.telegram_notifications import _is_public_http_url

MAX_CREATE_COUNT = 20
DEFAULT_CREATE_COUNT = 10
DEFAULT_CATEGORY = "celebrity"
DEFAULT_LANGUAGE = "en"
DEFAULT_CARD_LAYOUT = "flag_hero"
DEFAULT_TARGET_DURATION = 60
MIN_TARGET_DURATION = 15
MAX_TARGET_DURATION = 180
SUPPORTED_CATEGORIES = {"celebrity"}


async def handle_telegram_command(
    *,
    telegram_user_id: int,
    username: str = "",
    text: str,
) -> str | TelegramResponse:
    """Handle one Telegram text command and return a response message."""
    user = await production_tasks.get_authorized_user(telegram_user_id)
    if not user:
        return (
            "You are not authorized to use this production bot. "
            "Ask an admin to allow your Telegram user id."
        )

    parts = text.strip().split()
    command = parts[0].lower() if parts else "/help"
    if "@" in command:
        command = command.split("@", 1)[0]

    if command in {"/start", "/help"}:
        return _help_message(user)
    if command == "/create":
        return await _handle_create(telegram_user_id=telegram_user_id, args=parts[1:])
    if command == "/channels":
        return await channel_list_response(telegram_user_id)
    if command == "/reviews":
        return await _handle_reviews(telegram_user_id=telegram_user_id)
    if command == "/uploads":
        return await _handle_uploads(telegram_user_id=telegram_user_id)
    if command in {"/status", "/batches"}:
        return await _handle_status(telegram_user_id=telegram_user_id)

    return "Unknown command. Use /help to see available commands."


def _help_message(user: dict) -> str:
    role = user.get("role", "producer")
    return (
        "Y5E Production Bot\n"
        f"Role: {role}\n"
        "Commands:\n"
        "/create <count> [category] [language] [layout] [--duration seconds]\n"
        "/status\n"
        "/batches\n"
        "/channels\n"
        "/reviews\n"
        "/uploads\n"
        "No daily quota is enforced. Max per command is 20."
    )


async def _handle_create(*, telegram_user_id: int, args: list[str]) -> str | TelegramResponse:
    duration_result = _parse_duration(args)
    if isinstance(duration_result, str):
        return duration_result
    positional_args, target_duration = duration_result

    count = _parse_count(positional_args[0] if positional_args else "")
    if count > MAX_CREATE_COUNT:
        return f"Max per command is {MAX_CREATE_COUNT}. Send multiple /create commands for larger runs."

    category = positional_args[1].strip().lower() if len(positional_args) >= 2 else DEFAULT_CATEGORY
    language = positional_args[2].strip().lower() if len(positional_args) >= 3 else DEFAULT_LANGUAGE
    card_layout = positional_args[3].strip() if len(positional_args) >= 4 else DEFAULT_CARD_LAYOUT
    if category not in SUPPORTED_CATEGORIES:
        return "Only category 'celebrity' is supported in v1."

    batch = await production_tasks.create_production_batch(
        owner_telegram_user_id=telegram_user_id,
        requested_count=count,
        category=category,
        language=language,
        card_layout=card_layout,
        target_duration=target_duration,
    )
    return (
        "Đã nhận yêu cầu sản xuất\n"
        f"Số lượng: {batch['requested_count']} video\n"
        f"Thời lượng mục tiêu: {batch['target_duration']} giây/video\n"
        f"Nội dung: {category} | {language} | {card_layout}\n"
        "Kênh YouTube: chọn khi approve từng video\n"
        "Queue công bằng: video của các user sẽ được xử lý xen kẽ."
    )


async def _handle_status(*, telegram_user_id: int) -> str:
    summary = await production_tasks.user_queue_summary(telegram_user_id)
    batches = await production_tasks.list_user_batches(telegram_user_id, limit=5)
    lines = [
        "Tình trạng sản xuất",
        f"Đang chờ: {summary.get('queued', 0)}",
        f"Đang render: {summary.get('running', 0)}",
        f"Chờ duyệt: {summary.get('pending_review', 0)}",
        f"Đã approve: {summary.get('approved', 0)}",
        f"Đã reject: {summary.get('rejected', 0)}",
        f"Lỗi: {summary.get('failed', 0)}",
        "",
        "Các batch gần đây:",
    ]
    if not batches:
        lines.append("Chưa có batch nào.")
    for index, batch in enumerate(batches, start=1):
        lines.append(
            (
                f"{index}. {batch.get('completed_count', 0)}/{batch.get('requested_count', 0)} hoàn tất, "
                f"{batch.get('failed_count', 0)} lỗi, "
                f"trạng thái: {batch.get('status', '')}"
            )
        )
    return "\n".join(lines)


async def _handle_reviews(*, telegram_user_id: int) -> TelegramResponse:
    tasks = await production_tasks.list_pending_review_tasks(telegram_user_id, limit=10)
    if not tasks:
        return TelegramResponse("Hiện không có video nào chờ duyệt.")

    lines = ["Video chờ duyệt"]
    keyboard_rows: list[list[dict[str, str]]] = []
    base_url = str(get_settings().public_base_url).rstrip("/")
    can_open_video = _is_public_http_url(base_url)
    for index, task in enumerate(tasks, start=1):
        review_id = str(task.get("review_id") or "")
        title = str(task.get("title") or task.get("youtube_title") or task.get("topic_title") or "").strip()
        if not title and review_id:
            title = await _review_display_title(review_id)
        label = title or f"Video #{index}"
        lines.append(f"{index}. {label}")
        row: list[dict[str, str]] = []
        if can_open_video:
            row.append({"text": f"Preview {index}", "url": f"{base_url}/api/reviews/{review_id}/video"})
        row.append({"text": f"Approve {index}", "callback_data": f"rv:ok:{review_id}"})
        keyboard_rows.append(row)
    return TelegramResponse("\n".join(lines), {"inline_keyboard": keyboard_rows})


async def _review_display_title(review_id: str) -> str:
    try:
        review = await get_review(review_id)
    except (KeyError, OSError, ValueError):
        return ""
    youtube = review.get("youtube") if isinstance(review, dict) else {}
    selected = review.get("selected_metadata") if isinstance(review, dict) else {}
    content = review.get("content_contract") if isinstance(review, dict) else {}
    title = str(
        (youtube or {}).get("title")
        or (selected or {}).get("title")
        or (content or {}).get("youtube_title")
        or (content or {}).get("title")
        or ""
    ).strip()
    return _shorten_line(title, limit=72)


def _shorten_line(value: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


async def _handle_uploads(*, telegram_user_id: int) -> str:
    jobs = await youtube_upload_jobs.list_owner_jobs(telegram_user_id, limit=10)
    if not jobs:
        return "Chưa có upload YouTube nào."
    lines = ["YouTube uploads"]
    for index, job in enumerate(jobs, start=1):
        status = str(job.get("status") or "unknown").replace("_", " ").title()
        channel = str(job.get("channel_title") or "YouTube")
        url = str(job.get("youtube_url") or "")
        error_code = str(job.get("error_code") or "")
        suffix = f"\n   Link: {url}" if url else (f"\n   Cần xử lý: {error_code}" if error_code else "")
        lines.append(f"{index}. {status} | {channel}{suffix}")
    return "\n".join(lines)


def _parse_count(value: str) -> int:
    if not value:
        return DEFAULT_CREATE_COUNT
    try:
        count = int(value)
    except ValueError:
        return DEFAULT_CREATE_COUNT
    return max(1, count)


def _parse_duration(args: list[str]) -> tuple[list[str], int] | str:
    positional_args: list[str] = []
    target_duration = DEFAULT_TARGET_DURATION
    index = 0
    while index < len(args):
        token = args[index].strip()
        if token == "--duration":
            if index + 1 >= len(args):
                return "Usage: /create <count> [category] [language] [layout] --duration <seconds>"
            parsed = _parse_duration_value(args[index + 1])
            if isinstance(parsed, str):
                return parsed
            target_duration = parsed
            index += 2
            continue
        if token.startswith("--duration="):
            parsed = _parse_duration_value(token.split("=", 1)[1])
            if isinstance(parsed, str):
                return parsed
            target_duration = parsed
            index += 1
            continue
        positional_args.append(token)
        index += 1
    return positional_args, target_duration


def _parse_duration_value(value: str) -> int | str:
    try:
        duration = int(value)
    except ValueError:
        return "Duration must be a whole number of seconds."
    if duration < MIN_TARGET_DURATION or duration > MAX_TARGET_DURATION:
        return f"Duration must be between {MIN_TARGET_DURATION} and {MAX_TARGET_DURATION} seconds."
    return duration
