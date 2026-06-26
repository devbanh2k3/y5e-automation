"""API cost tracking — logs usage and computes daily/monthly spend."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core import database as db

logger = logging.getLogger(__name__)

# Simple per-token pricing (USD per 1 K tokens).  Adjust as needed.
_PRICING: dict[str, float] = {
    "gpt-4o":       0.005,
    "gpt-4o-mini":  0.00015,
    "gpt-4":        0.03,
    "gpt-3.5-turbo": 0.0005,
}

_DEFAULT_PRICE_PER_1K: float = 0.002


def _estimate_cost(model: str, tokens: int) -> float:
    """Estimate the USD cost for a given model and token count."""
    rate = _PRICING.get(model, _DEFAULT_PRICE_PER_1K)
    return (tokens / 1_000) * rate


async def log_api_call(
    agent: str,
    provider: str,
    model: str,
    tokens: int,
    is_fallback: bool = False,
) -> None:
    """Record an API call in the ``api_usage`` table.

    Args:
        agent: Name of the agent or module that made the call.
        provider: API provider identifier (e.g. ``openai``, ``local``).
        model: Model name used for the call.
        tokens: Total tokens consumed (prompt + completion).
        is_fallback: Whether the fallback endpoint was used.
    """
    await db.execute(
        """
        INSERT INTO api_usage (agent_name, api_provider, model_used, tokens_used, is_fallback, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        agent,
        provider,
        model,
        tokens,
        is_fallback,
        datetime.now(timezone.utc),
    )
    cost = _estimate_cost(model, tokens)
    logger.debug(
        "API call logged: agent=%s model=%s tokens=%d cost=$%.4f fallback=%s",
        agent, model, tokens, cost, is_fallback,
    )


async def get_daily_cost() -> float:
    """Return the estimated API cost (USD) for today (UTC).

    Returns:
        A float representing today's total estimated spend.
    """
    rows = await db.fetch(
        """
        SELECT model_used, SUM(tokens_used) AS total_tokens
        FROM api_usage
        WHERE created_at >= CURRENT_DATE
        GROUP BY model_used
        """
    )
    total = 0.0
    for row in rows:
        total += _estimate_cost(row["model_used"], row["total_tokens"])
    return round(total, 4)


async def get_monthly_cost() -> float:
    """Return the estimated API cost (USD) for the current calendar month.

    Returns:
        A float representing this month's total estimated spend.
    """
    rows = await db.fetch(
        """
        SELECT model_used, SUM(tokens_used) AS total_tokens
        FROM api_usage
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY model_used
        """
    )
    total = 0.0
    for row in rows:
        total += _estimate_cost(row["model_used"], row["total_tokens"])
    return round(total, 4)


async def get_usage_summary() -> dict:
    """Return a summary of API usage for the current day.

    Returns:
        A dict with ``daily_cost``, ``monthly_cost``, ``calls_today``,
        and ``tokens_today`` keys.
    """
    daily_cost = await get_daily_cost()
    monthly_cost = await get_monthly_cost()

    stats = await db.fetchrow(
        """
        SELECT COUNT(*) AS calls_today, COALESCE(SUM(tokens_used), 0) AS tokens_today
        FROM api_usage
        WHERE created_at >= CURRENT_DATE
        """
    )
    calls_today = stats["calls_today"] if stats else 0
    tokens_today = stats["tokens_today"] if stats else 0

    return {
        "daily_cost": daily_cost,
        "monthly_cost": monthly_cost,
        "calls_today": calls_today,
        "tokens_today": tokens_today,
    }
