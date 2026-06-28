"""Telegram remote-control command handling for production tasks."""

from __future__ import annotations

from core import production_tasks, youtube_channels
from services.telegram_channels import TelegramResponse, channel_list_response

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

    selected_channel = await youtube_channels.consume_selected_channel(telegram_user_id)
    if not selected_channel:
        return await channel_list_response(
            telegram_user_id,
            prompt="Select a YouTube channel, then send /create again.",
        )

    batch = await production_tasks.create_production_batch(
        owner_telegram_user_id=telegram_user_id,
        requested_count=count,
        category=category,
        language=language,
        card_layout=card_layout,
        target_duration=target_duration,
        youtube_channel_id=str(selected_channel["youtube_channel_id"]),
    )
    return (
        f"Batch created: {batch['batch_id']}\n"
        f"{batch['requested_count']} tasks queued.\n"
        f"Target duration: {batch['target_duration']}s.\n"
        f"YouTube channel: {selected_channel['title']}.\n"
        "Fair queue enabled. Your videos will be interleaved with other users."
    )


async def _handle_status(*, telegram_user_id: int) -> str:
    summary = await production_tasks.user_queue_summary(telegram_user_id)
    batches = await production_tasks.list_user_batches(telegram_user_id, limit=5)
    lines = [
        "Your production status:",
        f"Queued: {summary.get('queued', 0)}",
        f"Running: {summary.get('running', 0)}",
        f"Pending review: {summary.get('pending_review', 0)}",
        f"Approved: {summary.get('approved', 0)}",
        f"Rejected: {summary.get('rejected', 0)}",
        f"Failed: {summary.get('failed', 0)}",
        "",
        "Recent batches:",
    ]
    if not batches:
        lines.append("No batches yet.")
    for batch in batches:
        lines.append(
            (
                f"{batch.get('batch_id', '')}: "
                f"{batch.get('completed_count', 0)}/{batch.get('requested_count', 0)} done, "
                f"{batch.get('failed_count', 0)} failed, "
                f"status={batch.get('status', '')}"
            )
        )
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
