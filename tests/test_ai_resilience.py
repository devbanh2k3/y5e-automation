import httpx
import pytest

from core.ai_resilience import AIJsonFailure, safe_generate_json


@pytest.mark.asyncio
async def test_safe_generate_json_extracts_fenced_json():
    async def generate(**kwargs):
        return 'Result:\n```json\n{"items":[{"name":"Adele"}]}\n```'

    result = await safe_generate_json(generate, prompt="plan", system="json")

    assert result.value == {"items": [{"name": "Adele"}]}
    assert result.attempts == 1
    assert result.json_repairs == 0


@pytest.mark.asyncio
async def test_safe_generate_json_repairs_malformed_json_once():
    responses = iter(
        ['{"items":[{"name":"Adele",}]}', '{"items":[{"name":"Adele"}]}']
    )

    async def generate(**kwargs):
        return next(responses)

    result = await safe_generate_json(
        generate,
        prompt="plan",
        system="json",
        json_repair_attempts=1,
    )

    assert result.value["items"][0]["name"] == "Adele"
    assert result.json_repairs == 1


@pytest.mark.asyncio
async def test_safe_generate_json_returns_structured_transport_failure_after_budget():
    attempts = 0

    async def generate(**kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow")

    async def no_sleep(delay):
        return None

    with pytest.raises(AIJsonFailure) as exc_info:
        await safe_generate_json(
            generate,
            prompt="plan",
            system="json",
            transport_attempts=2,
            sleep=no_sleep,
        )

    assert exc_info.value.category == "transport_exhausted"
    assert exc_info.value.attempts == 2
    assert attempts == 2
