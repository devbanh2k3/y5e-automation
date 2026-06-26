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
    assert "top 10" in contract["title"].lower()
    assert "giàu nhất" in contract["title"].lower()
    assert "estimated net worth" in contract["hook"].lower()
    assert len(contract["scenes"]) >= 5
    assert contract["thumbnail_prompt"]
    assert contract["youtube_title"]
    assert contract["youtube_description"]
    assert "data comparison" in contract["youtube_tags"]
    assert "nguoi noi tieng" in contract["youtube_tags"]
    assert all(scene["image_prompt"] for scene in contract["scenes"])
    assert all(scene["voiceover"] for scene in contract["scenes"])
    assert contract["scenes"][0]["statusText"].startswith("#10")
    assert contract["scenes"][-1]["statusText"].startswith("#1")
    assert contract["scenes"][0]["countryCode"] == "CA"
    assert contract["scenes"][0]["countryLabel"] == "CANADA"
    assert contract["scenes"][0]["metricLabel"] == "NET WORTH"
    assert contract["scenes"][0]["metricValue"] == "550M USD"
    assert all("M USD" in scene["voiceover"] for scene in contract["scenes"])


@pytest.mark.asyncio
async def test_content_agent_builds_country_comparison_comedy_contract():
    agent = ContentAgent()

    contract = await agent.run(
        niche="country_comparison_comedy",
        language="vi",
        subject="parents reward good grades",
    )

    validate_content_contract_v2(contract)

    assert contract["niche"] == "country_comparison_comedy"
    assert contract["cardLayout"] == "flag_hero"
    assert "different countries" in contract["title"].lower()
    assert "entertainment" in contract["youtube_description"].lower()
    assert "country comparison" in contract["youtube_tags"]
    assert len(contract["scenes"]) == 10
    assert contract["scenes"][0]["countryCode"] == "JP"
    assert contract["scenes"][0]["countryLabel"] == "JAPAN"
    assert contract["scenes"][0]["metricLabel"] == "REACTION"
    assert contract["scenes"][0]["metricValue"]
    assert "2D animated" in contract["scenes"][0]["image_prompt"]
    assert all(len(scene["voiceover"].split()) <= 24 for scene in contract["scenes"])
