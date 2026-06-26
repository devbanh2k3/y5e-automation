import pytest

from agents.content_agent import ContentAgent
from core.video_contract import validate_content_contract_v2


@pytest.mark.asyncio
async def test_content_agent_builds_celebrity_mvp_contract():
    agent = ContentAgent()

    contract = await agent.run(
        niche="celebrity",
        language="vi",
        subject="người nổi tiếng",
    )

    validate_content_contract_v2(contract)

    assert contract["niche"] == "celebrity"
    assert contract["language"] == "vi"
    assert "người nổi tiếng" in contract["title"].lower()
    assert len(contract["scenes"]) >= 5
    assert contract["thumbnail_prompt"]
    assert contract["youtube_title"]
    assert contract["youtube_description"]
    assert "nguoi noi tieng" in contract["youtube_tags"]
    assert all(scene["image_prompt"] for scene in contract["scenes"])
    assert all(scene["voiceover"] for scene in contract["scenes"])
