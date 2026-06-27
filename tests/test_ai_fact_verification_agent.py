import pytest

from agents.ai_fact_verification_agent import AIFactVerificationAgent
from core.fact_verification import FactVerificationError


def content_contract():
    return {
        "contentFormat": "count_comparison",
        "metricScope": "public Grammy records",
        "timeScope": "2026",
        "scenes": [
            {
                "title": "Taylor Swift",
                "factClaim": "Taylor Swift has 14 Grammy wins",
                "factValue": "14",
                "factUnit": "awards",
                "factAsOf": "2026",
                "factContext": "Grammy wins through 2026",
                "metricLabel": "GRAMMY WINS",
                "image_prompt": "must not leak into fact prompt",
            }
        ],
    }


def verified_response(confidence=0.92):
    return {
        "scene_index": 0,
        "person_name": "Taylor Swift",
        "metric_label": "GRAMMY WINS",
        "original_value": "14",
        "verified_value": "14",
        "unit": "awards",
        "as_of": "2026",
        "status": "verified",
        "confidence": confidence,
        "reason": "Consistent with established public knowledge",
        "knowledge_cutoff_risk": "low",
    }


@pytest.mark.asyncio
async def test_agent_sends_structured_claims_and_returns_contract(monkeypatch):
    agent = AIFactVerificationAgent()
    captured = {}

    async def fake_ai_json(prompt, system=None, **kwargs):
        captured["prompt"] = prompt
        return {"items": [verified_response()]}

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    result = await agent.run(content_contract=content_contract())

    assert result["status"] == "ai_verified"
    assert "factClaim" in captured["prompt"]
    assert "image_prompt" not in captured["prompt"]


@pytest.mark.asyncio
async def test_agent_rejects_low_confidence(monkeypatch):
    agent = AIFactVerificationAgent()

    async def fake_ai_json(prompt, system=None, **kwargs):
        return {"items": [verified_response(confidence=0.6)]}

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    with pytest.raises(FactVerificationError):
        await agent.run(content_contract=content_contract())
