"""Bounded recovery helpers for AI calls that must return JSON objects."""

from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx


@dataclass(frozen=True)
class AIJsonResult:
    """Successful JSON response plus recovery diagnostics."""

    value: dict[str, Any]
    attempts: int
    json_repairs: int


class AIJsonFailure(RuntimeError):
    """A bounded AI JSON operation could not recover."""

    def __init__(self, message: str, *, category: str, attempts: int) -> None:
        super().__init__(message)
        self.category = category
        self.attempts = attempts


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract one JSON object from plain, fenced, or prose-wrapped output."""

    candidates = [raw.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    braced = re.search(r"\{.*\}", raw, re.DOTALL)
    if braced:
        candidates.append(braced.group(0))

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("AI response does not contain a valid JSON object")


def _is_retryable_transport(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )


async def safe_generate_json(
    generate: Callable[..., Awaitable[str]],
    *,
    prompt: str,
    system: str,
    transport_attempts: int = 3,
    json_repair_attempts: int = 2,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AIJsonResult:
    """Call a text generator and recover bounded transport/JSON failures."""

    transport_attempts = max(1, transport_attempts)
    json_repair_attempts = max(0, json_repair_attempts)
    attempts = 0
    repairs = 0
    current_prompt = prompt

    while attempts < transport_attempts:
        attempts += 1
        try:
            raw = await generate(
                prompt=current_prompt,
                system=system,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            if not _is_retryable_transport(exc):
                raise AIJsonFailure(
                    str(exc), category="permanent_error", attempts=attempts
                ) from exc
            if attempts >= transport_attempts:
                raise AIJsonFailure(
                    str(exc), category="transport_exhausted", attempts=attempts
                ) from exc
            await sleep(min(4.0, (2 ** (attempts - 1)) + random.random()))
            continue

        try:
            value = extract_json_object(raw)
        except ValueError as exc:
            if repairs >= json_repair_attempts:
                raise AIJsonFailure(
                    str(exc), category="json_exhausted", attempts=attempts
                ) from exc
            repairs += 1
            current_prompt = (
                "Return corrected valid JSON only. Preserve all recoverable data from "
                "this malformed response:\n" + raw
            )
            continue
        return AIJsonResult(value=value, attempts=attempts, json_repairs=repairs)

    raise AIJsonFailure(
        "AI retry budget exhausted",
        category="transport_exhausted",
        attempts=attempts,
    )
