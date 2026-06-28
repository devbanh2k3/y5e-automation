"""Async PostgreSQL connection pool using asyncpg."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from core.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_db() -> asyncpg.Pool:
    """Create and cache the asyncpg connection pool.

    Returns:
        The initialised connection pool.
    """
    global _pool  # noqa: PLW0603

    if _pool is not None:
        return _pool

    settings = get_settings()
    dsn = settings.asyncpg_dsn

    logger.info("Initialising database pool → %s", dsn.split("@")[-1])

    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
        statement_cache_size=100,
    )

    logger.info("Database pool created successfully.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool or initialise a new one.

    Returns:
        The active asyncpg connection pool.

    Raises:
        RuntimeError: If the pool cannot be created.
    """
    if _pool is None:
        return await init_db()
    return _pool


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Yield one connection inside an atomic PostgreSQL transaction."""
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            yield connection


async def execute(query: str, *args: Any) -> str:
    """Execute a single SQL statement (INSERT / UPDATE / DELETE).

    Args:
        query: SQL query with $1, $2 … placeholders.
        *args: Positional arguments matching the placeholders.

    Returns:
        The command tag returned by PostgreSQL (e.g. ``INSERT 0 1``).
    """
    pool = await get_pool()
    result: str = await pool.execute(query, *args)
    return result


async def fetch(query: str, *args: Any) -> list[dict[str, Any]]:
    """Fetch multiple rows as a list of dicts.

    Args:
        query: SQL query with $1, $2 … placeholders.
        *args: Positional arguments matching the placeholders.

    Returns:
        A list of dicts, one per row.
    """
    pool = await get_pool()
    rows: list[asyncpg.Record] = await pool.fetch(query, *args)
    return [dict(row) for row in rows]


async def fetchrow(query: str, *args: Any) -> dict[str, Any] | None:
    """Fetch a single row as a dict.

    Args:
        query: SQL query with $1, $2 … placeholders.
        *args: Positional arguments matching the placeholders.

    Returns:
        A dict for the first matching row, or ``None`` if no row matched.
    """
    pool = await get_pool()
    row: asyncpg.Record | None = await pool.fetchrow(query, *args)
    return dict(row) if row else None


async def fetchval(query: str, *args: Any) -> Any:
    """Fetch a single scalar value from the first column of the first row.

    Args:
        query: SQL query with $1, $2 … placeholders.
        *args: Positional arguments matching the placeholders.

    Returns:
        The scalar value, or ``None``.
    """
    pool = await get_pool()
    return await pool.fetchval(query, *args)


async def close_db() -> None:
    """Gracefully close the connection pool."""
    global _pool  # noqa: PLW0603

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")
