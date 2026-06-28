"""Telegram remote-control command handling for production tasks."""

from __future__ import annotations

from core import production_tasks

MAX_CREATE_COUNT = 20
DEFAULT_CREATE_COUNT = 10
DEFAULT_CATEGORY = "celebrity"
DEFAULT_LANGUAGE = "en"
DEFAULT_CARD_LAYOUT = "flag_hero"
SUPPORTED_CATEGORIES = {"celebrity"}


async def handle_telegram_command(
    *,
    telegram_user_id: int,
    username: str = "",
    text: str,
) -> str:
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
    if command in {"/status", "/batches"}:
        return await _handle_status(telegram_user_id=telegram_user_id)

    return "Unknown command. Use /help to see available commands."


def _help_message(user: dict) -> str:
    role = user.get("role", "producer")
    return (
        "Y5E Production Bot\n"
        f"Role: {role}\n"
        "Commands:\n"
        "/create <count> [category] [language] [layout]\n"
        "/status\n"
        "/batches\n"
        "No daily quota is enforced. Max per command is 20."
    )


async def _handle_create(*, telegram_user_id: int, args: list[str]) -> str:
    count = _parse_count(args[0] if args else "")
    if count > MAX_CREATE_COUNT:
        return f"Max per command is {MAX_CREATE_COUNT}. Send multiple /create commands for larger runs."

    category = args[1].strip().lower() if len(args) >= 2 else DEFAULT_CATEGORY
    language = args[2].strip().lower() if len(args) >= 3 else DEFAULT_LANGUAGE
    card_layout = args[3].strip() if len(args) >= 4 else DEFAULT_CARD_LAYOUT
    if category not in SUPPORTED_CATEGORIES:
        return "Only category 'celebrity' is supported in v1."

    batch = await production_tasks.create_production_batch(
        owner_telegram_user_id=telegram_user_id,
        requested_count=count,
        category=category,
        language=language,
        card_layout=card_layout,
    )
    return (
        f"Batch created: {batch['batch_id']}\n"
        f"{batch['requested_count']} tasks queued.\n"
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
