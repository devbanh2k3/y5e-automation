#!/usr/bin/env python3
"""Apply SQL migrations from db/migrations using asyncpg."""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

import asyncpg

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import get_settings

MIGRATIONS_DIR = ROOT_DIR / "db" / "migrations"


def migration_sort_key(path: Path) -> tuple[int, str]:
    """Keep additive chat routing after the base Telegram production migration."""
    if "chat-routing" in path.name:
        return (1, path.name)
    return (0, path.name)


def migration_files() -> list[Path]:
    """Return SQL migrations in deterministic dependency-safe order."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=migration_sort_key)


async def apply_migrations() -> list[str]:
    """Apply pending migrations and return applied filenames."""
    settings = get_settings()
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied: list[str] = []
        for path in migration_files():
            already_applied = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE filename = $1",
                path.name,
            )
            if already_applied:
                continue

            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)",
                    path.name,
                )
            applied.append(path.name)
        return applied
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    applied = asyncio.run(apply_migrations())
    if applied:
        print("Applied migrations:")
        for filename in applied:
            print(f"- {filename}")
    else:
        print("No pending migrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
