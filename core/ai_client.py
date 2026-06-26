"""Unified AI client with primary/fallback endpoints (OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx

from core.config import get_settings
from core.cost_tracker import log_api_call

logger = logging.getLogger(__name__)

# Module-level reusable client (created lazily)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return a module-level async HTTP client (singleton)."""
    global _client  # noqa: PLW0603
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    return _client


def is_running_in_docker() -> bool:
    """Return True when running inside a Docker container."""
    return Path("/.dockerenv").exists()


def resolve_docker_host_url(base_url: str, *, running_in_docker: bool | None = None) -> str:
    """Map host-local AI router URLs to the Docker host when needed."""
    in_docker = is_running_in_docker() if running_in_docker is None else running_in_docker
    if not in_docker:
        return base_url

    parsed = urlsplit(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return base_url

    netloc = "host.docker.internal"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response.

    Handles cases where the model wraps JSON in markdown code fences.

    Args:
        text: Raw text from the model's reply.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON could be extracted.
    """
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON inside markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to find the first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}")


def parse_sse_chat_completion(text: str) -> tuple[str, int]:
    """Parse OpenAI-compatible streaming SSE chat completion text."""
    content_parts: list[str] = []
    total_tokens = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue

        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        usage = event.get("usage") or {}
        total_tokens = int(usage.get("total_tokens") or total_tokens)

        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                content_parts.append(content)

    return "".join(content_parts), total_tokens


def parse_chat_completion_response(resp: httpx.Response) -> tuple[str, int]:
    """Parse a chat completion response from JSON or SSE providers."""
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type or resp.text.lstrip().startswith("data:"):
        return parse_sse_chat_completion(resp.text)

    data = resp.json()
    content: str = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    total_tokens: int = usage.get("total_tokens", 0)
    return content, total_tokens


async def _call_endpoint(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    response_format: dict[str, str] | None = None,
) -> tuple[str, int]:
    """Make a single OpenAI-compatible chat completion request.

    Retries automatically on 429 (rate-limit) and 503 (service unavailable)
    errors with exponential backoff (max 6 retries, wait = 5 * (attempt+1) s).

    Args:
        base_url: The base URL (e.g. ``https://api.openai.com/v1``).
        api_key: Bearer token.
        model: Model identifier.
        messages: Chat messages list.
        temperature: Sampling temperature.
        response_format: Optional response format dict (e.g. ``{"type": "json_object"}``).

    Returns:
        A tuple of ``(response_text, total_tokens)``.

    Raises:
        httpx.HTTPStatusError: On non-retryable 4xx/5xx responses.
        httpx.TimeoutException: On timeout.
    """
    client = _get_client()
    url = f"{base_url.rstrip('/')}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    max_retries = 6
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

            return parse_chat_completion_response(resp)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503) and attempt < max_retries:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "Retryable HTTP %d from %s (attempt %d/%d); waiting %ds",
                    exc.response.status_code, url, attempt + 1, max_retries, wait,
                )
                await asyncio.sleep(wait)
                continue
            raise


async def generate(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    agent_name: str = "unknown",
    response_format: dict[str, str] | None = None,
) -> str:
    """Generate a text completion, falling back to the secondary endpoint.

    Args:
        prompt: The user-role prompt.
        system: Optional system-role message.
        model: Override model name.  Defaults to the primary model.
        temperature: Sampling temperature.
        agent_name: Name used for cost-tracking attribution.
        response_format: Optional response format dict forwarded to the API.

    Returns:
        The model's reply as a string.
    """
    settings = get_settings()

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    primary_model = model or settings.primary_model
    primary_api_base = resolve_docker_host_url(settings.primary_api_base)
    fallback_api_base = resolve_docker_host_url(settings.fallback_api_base)

    # ── Attempt 1: primary endpoint ──────────────────────────
    try:
        content, tokens = await _call_endpoint(
            base_url=primary_api_base,
            api_key=settings.primary_api_key,
            model=primary_model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        await log_api_call(
            agent=agent_name,
            provider=primary_api_base,
            model=primary_model,
            tokens=tokens,
            is_fallback=False,
        )
        return content

    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning(
            "Primary AI endpoint failed (%s); falling back. Error: %s",
            primary_api_base,
            exc,
        )

    # ── Attempt 2: fallback endpoint ─────────────────────────
    fallback_model = model or settings.fallback_model
    try:
        content, tokens = await _call_endpoint(
            base_url=fallback_api_base,
            api_key=settings.fallback_api_key,
            model=fallback_model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        await log_api_call(
            agent=agent_name,
            provider=fallback_api_base,
            model=fallback_model,
            tokens=tokens,
            is_fallback=True,
        )
        return content

    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.error("Fallback AI endpoint also failed: %s", exc)
        raise


async def generate_json(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    agent_name: str = "unknown",
) -> dict[str, Any]:
    """Generate a response and parse it as JSON.

    The system prompt is automatically augmented to instruct the model
    to return valid JSON.  The API call includes
    ``response_format: {"type": "json_object"}`` for providers that
    support structured output.

    Args:
        prompt: The user-role prompt.
        system: Optional system-role message (JSON instruction appended).
        model: Override model name.
        temperature: Sampling temperature (lower default for JSON).
        agent_name: Name used for cost-tracking attribution.

    Returns:
        Parsed dict from the model's response.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    json_instruction = (
        "You MUST respond with valid JSON only. "
        "Do not include any text outside the JSON object."
    )
    if system:
        full_system = f"{system}\n\n{json_instruction}"
    else:
        full_system = json_instruction
    # Enforce JSON output in the system prompt
    full_system += "\nYou MUST respond with valid JSON only."

    raw = await generate(
        prompt=prompt,
        system=full_system,
        model=model,
        temperature=temperature,
        agent_name=agent_name,
        response_format={"type": "json_object"},
    )

    return _extract_json(raw)


async def close_client() -> None:
    """Close the module-level HTTP client."""
    global _client  # noqa: PLW0603
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.info("AI HTTP client closed.")
