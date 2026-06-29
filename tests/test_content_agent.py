import pytest

from agents.content_agent import ContentAgent
from core.video_contract import validate_content_contract_v2


def awards_contract_payload(count=10):
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
                "title": f"#{count - index} Musician {index}",
                "voiceover": f"Musician {index} has a public award estimate.",
                "caption": f"AWARDS: {500 + index}",
                "image_prompt": f"real editorial photo of Musician {index}",
                "statusText": f"#{count - index} | {500 + index} awards",
                "countryCode": "US",
                "countryLabel": "UNITED STATES",
                "metricLabel": "AWARDS",
                "metricValue": str(500 + index),
                "sourceRequirement": "official award databases",
            }
            for index in range(count)
        ],
    }


@pytest.mark.parametrize(
    ("duration_target", "expected_scene_count"),
    [(40, 6), (60, 10), (90, 16), (120, 22), (300, 58), (600, 80)],
)
def test_desired_scene_count_for_duration(duration_target, expected_scene_count):
    assert ContentAgent.desired_scene_count_for_duration(duration_target) == expected_scene_count


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
            **scene,
            "factClaim": "Taylor Swift released her debut album in 2006",
            "factValue": "2006",
            "factUnit": "year",
            "factAsOf": "2026",
            "factContext": "official debut album release year",
        }
        for scene in payload["scenes"]
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
    payload = awards_contract_payload(count=16)

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
    assert len(contract["scenes"]) == 16


@pytest.mark.asyncio
async def test_content_agent_prompt_requests_duration_based_scene_count(monkeypatch):
    agent = ContentAgent()
    payload = awards_contract_payload(count=16)
    prompts = []

    async def fake_ai_json(prompt, system=None, **kwargs):
        prompts.append(prompt)
        return payload

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    await agent.run(
        niche="celebrity",
        language="en",
        selected_topic={"title": "Awards", "metric_label": "AWARDS"},
        duration_target=90,
    )

    assert "Use exactly 16 ranking scenes" in prompts[0]


@pytest.mark.asyncio
async def test_content_agent_generates_long_duration_contract_in_chunks(monkeypatch):
    agent = ContentAgent()
    prompts = []

    async def fake_ai_json(prompt, system=None, **kwargs):
        prompts.append(prompt)
        if "card scenes for ranks" not in prompt:
            return {
                "title": "Top 58 Most-Awarded Living Musicians",
                "hook": "Long ranking hook.",
                "target_audience": "Music fans.",
                "youtube_title": "Top 58 Most-Awarded Living Musicians",
                "youtube_description": "Long ranking based on public estimates.",
                "youtube_tags": ["celebrity", "music awards"],
                "thumbnail_prompt": "Awarded musicians",
                "scenes": [],
            }

        import re

        match = re.search(r"ranks #(\d+) down to #(\d+)", prompt)
        assert match is not None
        start_rank = int(match.group(1))
        end_rank = int(match.group(2))
        count = start_rank - end_rank + 1
        return {
            "scenes": [
                {
                    "title": f"#{start_rank - index} Musician {start_rank - index}",
                    "voiceover": f"Musician {start_rank - index} has a public award estimate.",
                    "caption": f"AWARDS: {start_rank - index}",
                    "image_prompt": f"real editorial photo of Musician {start_rank - index}",
                    "statusText": f"#{start_rank - index} | awards",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "AWARDS",
                    "metricValue": str(start_rank - index),
                    "sourceRequirement": "official award databases",
                }
                for index in range(count)
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="en",
        selected_topic={"title": "Awards", "metric_label": "AWARDS"},
        duration_target=300,
    )

    assert len(contract["scenes"]) == 58
    assert contract["scenes"][0]["title"].startswith("#58 ")
    assert contract["scenes"][-1]["title"].startswith("#1 ")
    assert len(prompts) == 5


@pytest.mark.asyncio
async def test_content_agent_long_fact_collection_uses_non_ranking_card_titles(monkeypatch):
    agent = ContentAgent()
    prompts = []

    async def fake_ai_json(prompt, system=None, **kwargs):
        prompts.append(prompt)
        if "Celebrity data-comparison card scenes" not in prompt:
            return {
                "title": "Celebrity First Roles and Breakout Facts",
                "hook": "Famous careers started in surprising places.",
                "target_audience": "Celebrity trivia viewers.",
                "youtube_title": "Celebrity First Roles and Breakout Facts",
                "youtube_description": "Public career milestone facts.",
                "youtube_tags": ["celebrity", "career facts"],
                "thumbnail_prompt": "Celebrity career facts",
                "scenes": [],
            }

        import re

        match = re.search(r"cards (\d+) through (\d+)", prompt)
        assert match is not None
        start_card = int(match.group(1))
        end_card = int(match.group(2))
        return {
            "scenes": [
                {
                    "title": f"Musician {card} first major role",
                    "voiceover": f"Musician {card} had an early public career milestone.",
                    "caption": f"FIRST ROLE: {2000 + card}",
                    "image_prompt": f"real editorial photo of Musician {card}",
                    "statusText": f"FACT {card} | first role",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "FIRST ROLE",
                    "metricValue": str(2000 + card),
                    "sourceRequirement": "public biography",
                    "factClaim": f"Musician {card} had a public first role in {2000 + card}.",
                    "factValue": str(2000 + card),
                    "factUnit": "YEAR",
                    "factAsOf": "2026",
                    "factContext": "public biography",
                }
                for card in range(start_card, end_card + 1)
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    contract = await agent.run(
        niche="celebrity",
        language="en",
        selected_topic={
            "title": "Celebrity First Roles and Breakout Facts",
            "metric_label": "FIRST ROLE",
            "content_format": "fact_collection",
            "metric_scope": "public biography milestones",
            "time_scope": "through 2026",
        },
        duration_target=300,
    )

    assert contract["contentFormat"] == "fact_collection"
    assert len(contract["scenes"]) == 58
    assert not any(scene["title"].startswith("#") for scene in contract["scenes"])
    assert contract["scenes"][0]["statusText"].startswith("FACT 1")
    assert "Use exactly 58 card scenes" in prompts[0]
    assert "ranking scenes" not in prompts[0]


@pytest.mark.asyncio
async def test_content_agent_rejects_duplicate_people_across_long_chunks(monkeypatch):
    agent = ContentAgent()

    async def fake_ai_json(prompt, system=None, **kwargs):
        if "Celebrity data-comparison card scenes" not in prompt:
            return {
                "title": "Celebrity Career Facts",
                "hook": "Career facts.",
                "target_audience": "Celebrity viewers.",
                "youtube_title": "Celebrity Career Facts",
                "youtube_description": "Career facts.",
                "youtube_tags": ["celebrity"],
                "thumbnail_prompt": "Celebrity facts",
                "scenes": [],
            }

        import re

        match = re.search(r"cards (\d+) through (\d+)", prompt)
        assert match is not None
        start_card = int(match.group(1))
        end_card = int(match.group(2))
        return {
            "scenes": [
                {
                    "title": "Taylor Swift career milestone" if card in {1, 16} else f"Artist {card} career milestone",
                    "voiceover": "A public career fact.",
                    "caption": "FACT",
                    "image_prompt": "real editorial photo",
                    "statusText": f"FACT {card}",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "CAREER",
                    "metricValue": "FACT",
                    "sourceRequirement": "public biography",
                    "factClaim": "A public career fact.",
                    "factValue": "FACT",
                    "factUnit": "CAREER",
                    "factAsOf": "2026",
                    "factContext": "public biography",
                }
                for card in range(start_card, end_card + 1)
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    with pytest.raises(ValueError, match="duplicate celebrity scenes"):
        await agent.run(
            niche="celebrity",
            language="en",
            selected_topic={
                "title": "Celebrity Career Facts",
                "metric_label": "CAREER",
                "content_format": "fact_collection",
                "metric_scope": "public biography milestones",
                "time_scope": "through 2026",
            },
            duration_target=300,
        )


def test_normalize_ai_celebrity_contract_rejects_too_few_duration_scenes():
    with pytest.raises(ValueError, match="requires at least 16 scenes"):
        ContentAgent._normalize_ai_celebrity_contract(
            raw_contract=awards_contract_payload(count=10),
            language="en",
            topic={"title": "Awards", "metric_label": "AWARDS"},
            card_layout="flag_hero",
            duration_target=90,
        )


def test_normalize_ai_celebrity_contract_repairs_missing_fact_fields():
    contract = ContentAgent._normalize_ai_celebrity_contract(
        raw_contract=awards_contract_payload(count=6),
        language="en",
        topic={
            "title": "Awards",
            "metric_label": "AWARDS",
            "content_format": "ranking",
            "metric_scope": "public award estimates",
            "time_scope": "through 2026",
        },
        card_layout="flag_hero",
        duration_target=40,
    )

    validate_content_contract_v2(contract)
    first = contract["scenes"][0]
    assert first["factClaim"]
    assert first["factValue"] == first["metricValue"]
    assert first["factUnit"] == "AWARDS"
    assert first["factAsOf"] == "through 2026"
    assert first["factContext"]


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
                *[
                    {
                        "title": f"#{rank} Singer {rank}",
                        "voiceover": f"#{rank} Singer {rank} has a large public following.",
                        "caption": f"{300 + rank}M followers",
                        "image_prompt": f"real editorial photo of Singer {rank}",
                        "statusText": f"#{rank} | {300 + rank}M followers",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "FOLLOWERS",
                        "metricValue": f"{300 + rank}M",
                        "sourceRequirement": "public social profile estimate",
                    }
                    for rank in range(9, 1, -1)
                ],
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
                    "title": f"#{10 - index} Athlete {index}",
                    "voiceover": f"#{10 - index} has a huge public following.",
                    "caption": "300M followers",
                    "image_prompt": "real editorial photo of an athlete",
                    "statusText": f"#{10 - index} | 300M",
                    "countryCode": "US",
                    "countryLabel": "USA",
                    "metricLabel": "FOLLOWERS",
                    "metricValue": "300M",
                    "sourceRequirement": "public social profile estimate",
                }
                for index in range(10)
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
