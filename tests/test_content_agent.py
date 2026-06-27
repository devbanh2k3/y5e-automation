import pytest

from agents.content_agent import ContentAgent
from core.video_contract import validate_content_contract_v2


def awards_contract_payload():
    return {
        "title": "Top 10 Most-Awarded Living Musicians",
        "hook": "Living music legends ranked by public award records.",
        "target_audience": "Music fans who enjoy data comparisons.",
        "youtube_title": "Top 10 Most-Awarded Living Musicians",
        "youtube_description": "A ranking based on public award records.",
        "youtube_tags": ["celebrity", "music awards"],
        "thumbnail_prompt": "Famous musicians with bold award totals",
        "scenes": [
            {
                "title": "#2 Taylor Swift",
                "voiceover": "Taylor Swift ranks second by public award totals.",
                "caption": "AWARDS: 600",
                "image_prompt": "real editorial photo of Taylor Swift",
                "statusText": "#2 | 600 awards",
                "countryCode": "US",
                "countryLabel": "UNITED STATES",
                "metricLabel": "AWARDS",
                "metricValue": "600",
                "sourceRequirement": "official award databases",
            },
            {
                "title": "#1 Beyonce",
                "voiceover": "Beyonce ranks first by public award totals.",
                "caption": "AWARDS: 700",
                "image_prompt": "real editorial photo of Beyonce",
                "statusText": "#1 | 700 awards",
                "countryCode": "US",
                "countryLabel": "UNITED STATES",
                "metricLabel": "AWARDS",
                "metricValue": "700",
                "sourceRequirement": "official award databases",
            },
        ],
    }


@pytest.mark.asyncio
async def test_content_agent_uses_selected_topic_without_regenerating_it(monkeypatch):
    agent = ContentAgent()
    selected = {
        "title": "Top 10 Most-Awarded Living Musicians",
        "angle": "living_musician_awards",
        "metric_label": "AWARDS",
    }
    prompts = []

    async def fake_ai_json(prompt, system=None, **kwargs):
        prompts.append(prompt)
        return awards_contract_payload()

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="en",
        subject="famous people",
        card_layout="flag_hero",
        selected_topic=selected,
    )

    assert len(prompts) == 1
    assert "Top 10 Most-Awarded Living Musicians" in prompts[0]
    assert contract["youtube_title"] == "Top 10 Most-Awarded Living Musicians"


@pytest.mark.asyncio
async def test_content_agent_preserves_selected_factual_format(monkeypatch):
    agent = ContentAgent()
    selected = {
        "title": "Celebrity Career Start Milestones",
        "angle": "career_start_age",
        "metric_label": "START YEAR",
        "content_format": "timeline",
        "metric_scope": "public debut years",
        "time_scope": "through 2026",
    }
    payload = awards_contract_payload()
    payload["scenes"] = [
        {
            **payload["scenes"][0],
            "factClaim": "Taylor Swift released her debut album in 2006",
            "factValue": "2006",
            "factUnit": "year",
            "factAsOf": "2026",
            "factContext": "official debut album release year",
        }
    ]

    async def fake_ai_json(prompt, system=None, **kwargs):
        return payload

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="en",
        selected_topic=selected,
    )

    assert contract["contentFormat"] == "timeline"
    assert contract["metricScope"] == "public debut years"
    assert contract["scenes"][0]["factValue"] == "2006"


@pytest.mark.asyncio
async def test_content_agent_uses_explicit_duration_target(monkeypatch):
    agent = ContentAgent()
    payload = awards_contract_payload()

    async def fake_ai_json(prompt, system=None, **kwargs):
        return payload

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="en",
        selected_topic={"title": "Awards", "metric_label": "AWARDS"},
        duration_target=90,
    )

    assert contract["duration_target"] == 90


@pytest.mark.asyncio
async def test_content_agent_builds_seeded_celebrity_mvp_contract(monkeypatch):
    agent = ContentAgent()

    async def fake_ai_json(prompt: str, system: str | None = None, **kwargs):
        raise RuntimeError("AI unavailable")

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="vi",
        subject="người nổi tiếng",
    )

    validate_content_contract_v2(contract)

    assert contract["niche"] == "celebrity"
    assert contract["language"] == "vi"
    assert contract["cardLayout"] == "flag_hero"
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
    assert "Madonna" not in {scene["title"].split(" ", 1)[1] for scene in contract["scenes"]}
    assert contract["scenes"][0]["statusText"].startswith("#10")
    assert contract["scenes"][-1]["statusText"].startswith("#1")
    assert contract["scenes"][0]["countryCode"] == "CA"
    assert contract["scenes"][0]["countryLabel"] == "CANADA"
    assert contract["scenes"][0]["metricLabel"] == "NET WORTH"
    assert contract["scenes"][0]["metricValue"] == "550M USD"
    assert all("M USD" in scene["voiceover"] for scene in contract["scenes"])


@pytest.mark.asyncio
async def test_content_agent_uses_ai_topic_and_ranking_for_celebrity(monkeypatch):
    agent = ContentAgent()
    calls: list[str] = []

    async def fake_ai_json(prompt: str, system: str | None = None, **kwargs):
        calls.append(prompt)
        if "Generate 1 optimized Celebrity topic" in prompt:
            return {
                "title": "Top 10 Most Followed Singers in 2026",
                "angle": "most_followed",
                "metric_label": "FOLLOWERS",
                "reason": "social proof and recognizable names",
            }
        return {
            "title": "Top 10 Most Followed Singers in 2026",
            "hook": "A ranking built from public follower estimates.",
            "target_audience": "Viewers who like celebrity data comparison.",
            "youtube_title": "Top 10 Most Followed Singers in 2026",
            "youtube_description": "Celebrity data comparison using public follower estimates.",
            "youtube_tags": ["celebrity", "data comparison", "most followed singers"],
            "thumbnail_prompt": "Celebrity ranking thumbnail with follower numbers",
            "scenes": [
                {
                    "title": "#2 Ariana Grande",
                    "voiceover": "#2 Ariana Grande has about 380M public followers.",
                    "caption": "380M followers",
                    "image_prompt": "real editorial photo of Ariana Grande",
                    "statusText": "#2 | 380M followers",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "380M",
                    "sourceRequirement": "public social profile estimate",
                },
                {
                    "title": "#1 Selena Gomez",
                    "voiceover": "#1 Selena Gomez has about 430M public followers.",
                    "caption": "430M followers",
                    "image_prompt": "real editorial photo of Selena Gomez",
                    "statusText": "#1 | 430M followers",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "430M",
                    "sourceRequirement": "public social profile estimate",
                },
            ],
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="vi",
        subject="người nổi tiếng",
    )

    validate_content_contract_v2(contract)

    assert len(calls) == 2
    assert contract["title"] == "Top 10 Most Followed Singers in 2026"
    assert contract["hook"] == "A ranking built from public follower estimates."
    assert contract["scenes"][0]["metricLabel"] == "FOLLOWERS"
    assert contract["scenes"][0]["title"] == "#2 Ariana Grande"
    assert contract["scenes"][-1]["title"] == "#1 Selena Gomez"
    assert "estimated net worth" not in contract["hook"].lower()


@pytest.mark.asyncio
async def test_content_agent_rejects_band_names_for_celebrity_person_contract(monkeypatch):
    agent = ContentAgent()

    async def fake_ai_json(prompt: str, system: str | None = None, **kwargs):
        if "Generate 1 optimized Celebrity topic" in prompt:
            return {
                "title": "Top 2 Most Followed Music Acts",
                "angle": "most_followed_music_acts",
                "metric_label": "FOLLOWERS",
                "reason": "music rankings",
            }
        return {
            "title": "Top 2 Most Followed Music Acts",
            "hook": "Music acts ranked by public estimates.",
            "target_audience": "Music ranking viewers.",
            "youtube_title": "Top 2 Most Followed Music Acts",
            "youtube_description": "Public estimates.",
            "youtube_tags": ["celebrity"],
            "thumbnail_prompt": "Music ranking thumbnail",
            "scenes": [
                {
                    "title": "#2 Coldplay",
                    "voiceover": "#2 Coldplay has a large following.",
                    "caption": "70M followers",
                    "image_prompt": "real editorial photo of Coldplay",
                    "statusText": "#2 | 70M",
                    "countryCode": "GB",
                    "countryLabel": "UNITED KINGDOM",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "70M",
                    "sourceRequirement": "public social profile estimate",
                },
                {
                    "title": "#1 U2",
                    "voiceover": "#1 U2 has a large following.",
                    "caption": "80M followers",
                    "image_prompt": "real editorial photo of U2",
                    "statusText": "#1 | 80M",
                    "countryCode": "IE",
                    "countryLabel": "IRELAND",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "80M",
                    "sourceRequirement": "public social profile estimate",
                },
            ],
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(niche="celebrity", language="en", subject="famous people")

    validate_content_contract_v2(contract)
    titles = {scene["title"].split(" ", 1)[1] for scene in contract["scenes"]}
    assert "Coldplay" not in titles
    assert "U2" not in titles
    assert "Celine Dion" in titles


@pytest.mark.asyncio
async def test_content_agent_normalizes_ai_country_labels(monkeypatch):
    agent = ContentAgent()

    async def fake_ai_json(prompt: str, system: str | None = None, **kwargs):
        if "Generate 1 optimized Celebrity topic" in prompt:
            return {
                "title": "Top 2 Most Followed Athletes",
                "angle": "most_followed_athletes",
                "metric_label": "FOLLOWERS",
                "reason": "recognizable global athletes",
            }
        return {
            "title": "Top 2 Most Followed Athletes",
            "hook": "Public follower estimates ranked fast.",
            "target_audience": "Sports and celebrity ranking viewers.",
            "youtube_title": "Top 2 Most Followed Athletes",
            "youtube_description": "Public follower estimates.",
            "youtube_tags": ["celebrity"],
            "thumbnail_prompt": "Athlete ranking thumbnail",
            "scenes": [
                {
                    "title": "#2 Athlete",
                    "voiceover": "#2 has a huge public following.",
                    "caption": "300M followers",
                    "image_prompt": "real editorial photo of an athlete",
                    "statusText": "#2 | 300M",
                    "countryCode": "US",
                    "countryLabel": "USA",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "300M",
                    "sourceRequirement": "public social profile estimate",
                }
            ],
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(niche="celebrity", language="vi", subject="athletes")

    validate_content_contract_v2(contract)
    assert contract["scenes"][0]["countryCode"] == "US"
    assert contract["scenes"][0]["countryLabel"] == "UNITED STATES"


@pytest.mark.asyncio
async def test_content_agent_falls_back_when_ai_celebrity_contract_is_invalid(monkeypatch):
    agent = ContentAgent()

    async def fake_ai_json(prompt: str, system: str | None = None, **kwargs):
        return {"title": ""}

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="vi",
        subject="người nổi tiếng",
    )

    validate_content_contract_v2(contract)

    assert "giàu nhất" in contract["title"].lower()
    assert contract["scenes"][0]["metricLabel"] == "NET WORTH"


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
