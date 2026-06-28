#!/usr/bin/env python3
"""Allow or disable Telegram users for remote production control."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.database import execute


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def allow_user(*, telegram_user_id: int, username: str = "", role: str = "producer") -> dict[str, Any]:
    """Allow a Telegram user to control production."""
    await execute(
        """
        INSERT INTO telegram_users (telegram_user_id, username, role, is_active, updated_at)
        VALUES ($1, $2, $3, TRUE, NOW())
        ON CONFLICT (telegram_user_id)
        DO UPDATE SET username = EXCLUDED.username,
                      role = EXCLUDED.role,
                      is_active = TRUE,
                      updated_at = NOW()
        """,
        telegram_user_id,
        username,
        role,
    )
    return {"telegram_user_id": telegram_user_id, "username": username, "role": role, "is_active": True}


async def disable_user(*, telegram_user_id: int) -> dict[str, Any]:
    """Disable a Telegram user."""
    await execute(
        """
        UPDATE telegram_users
        SET is_active = FALSE,
            updated_at = NOW()
        WHERE telegram_user_id = $1
        """,
        telegram_user_id,
    )
    return {"telegram_user_id": telegram_user_id, "is_active": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    allow = subparsers.add_parser("allow")
    allow.add_argument("telegram_user_id", type=int)
    allow.add_argument("--username", default="")
    allow.add_argument("--role", choices=["admin", "producer"], default="producer")

    disable = subparsers.add_parser("disable")
    disable.add_argument("telegram_user_id", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "allow":
        result = asyncio.run(
            allow_user(
                telegram_user_id=args.telegram_user_id,
                username=args.username,
                role=args.role,
            )
        )
    else:
        result = asyncio.run(disable_user(telegram_user_id=args.telegram_user_id))
    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

