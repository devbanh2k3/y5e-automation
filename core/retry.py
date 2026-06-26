"""Async retry decorator with exponential backoff."""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

from core.notifier import notify_error

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_retries: int = 3,
    backoff_base: int = 2,
    notify_on_failure: bool = True,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator that retries an async function with exponential backoff.

    Usage::

        @with_retry(max_retries=3, backoff_base=2)
        async def flaky_operation():
            ...

    Args:
        max_retries: Maximum number of retry attempts (excluding the
            initial call).
        backoff_base: Base for exponential backoff.  Wait time is
            ``backoff_base ** attempt`` seconds.
        notify_on_failure: If ``True``, send a Telegram notification
            on final failure.
        retryable_exceptions: Tuple of exception types that should
            trigger a retry.  All other exceptions propagate immediately.

    Returns:
        A decorator wrapping the target async function.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff_base ** attempt
                        logger.warning(
                            "[%s] Attempt %d/%d failed: %s — retrying in %ds",
                            func.__qualname__,
                            attempt + 1,
                            max_retries + 1,
                            exc,
                            wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "[%s] All %d attempts exhausted. Last error: %s",
                            func.__qualname__,
                            max_retries + 1,
                            exc,
                        )

            # Final failure
            if notify_on_failure and last_exc is not None:
                await notify_error(
                    agent=func.__qualname__,
                    error=str(last_exc)[:500],
                )

            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
