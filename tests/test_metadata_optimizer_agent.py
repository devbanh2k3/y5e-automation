import pytest

from agents.metadata_optimizer_agent import MetadataOptimizerAgent


def content_contract():
    return {
        "title": "Top 10 Most Followed Celebrities in 2026",
        "hook": "The follower gap is bigger than most people expect.",
        "language": "en",
        "youtube_title": "Top 10 Most Followed Celebrities in 2026",
        "youtube_description": "Public follower estimates.",
        "youtube_tags": ["celebrity", "data comparison"],
        "thumbnail_prompt": "Celebrity follower ranking thumbnail",
        "scenes": [
            {
                "title": "#2 Ariana Grande",
                "metricLabel": "FOLLOWERS",
                "metricValue": "380M",
                "factValue": "380M",
                "factAsOf": "2026",
            },
            {
                "title": "#1 Selena Gomez",
                "metricLabel": "FOLLOWERS",
                "metricValue": "430M",
                "factValue": "430M",
                "factAsOf": "2026",
            },
        ],
    }


@pytest.mark.asyncio
async def test_metadata_optimizer_fallback_creates_curiosity_variants(monkeypatch):
    agent = MetadataOptimizerAgent()

    async def fake_ai_json(prompt, system=None, **kwargs):
        raise RuntimeError("AI unavailable")

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    result = await agent.run(content_contract=content_contract())

    titles = [item["title"] for item in result["title_variants"]]
    assert len(titles) == 5
    assert any(not title.lower().startswith("top 10") for title in titles)
    assert result["selected_metadata"]["title"] == result["title_variants"][0]["title"]
    assert result["selected_metadata"]["description"]
    assert result["selected_metadata"]["tags"]
    assert result["thumbnail_text_suggestions"]
    assert result["search_keywords"]
    assert result["trend_angle"]
    assert all("score_total" in item for item in result["title_variants"])
    assert all("score_breakdown" in item for item in result["title_variants"])


@pytest.mark.asyncio
async def test_metadata_optimizer_normalizes_ai_variants(monkeypatch):
    agent = MetadataOptimizerAgent()

    async def fake_ai_json(prompt, system=None, **kwargs):
        return {
            "trend_angle": "2026 follower gap curiosity",
            "title_variants": [
                {
                    "title": "Celebrity Follower Numbers That Feel Unreal",
                    "format": "data_shock",
                    "score_breakdown": {
                        "search": 86,
                        "curiosity": 94,
                        "trend": 84,
                        "specificity": 90,
                        "safety": 96,
                    },
                },
                {
                    "title": "Top 10 Most Followed Celebrities in 2026",
                    "format": "direct_search",
                    "score_breakdown": {
                        "search": 95,
                        "curiosity": 65,
                        "trend": 82,
                        "specificity": 92,
                        "safety": 98,
                    },
                },
            ],
            "description_variants": [
                "A data comparison of public follower estimates in 2026.",
                "Celebrity follower counts ranked with public estimates.",
                "Who leads the biggest public social audience in 2026?",
                "extra description is ignored",
            ],
            "tags": ["celebrity", "data comparison", "followers"] + [f"tag{i}" for i in range(30)],
            "thumbnail_text_suggestions": ["430M?!", "THE GAP", "WHO LEADS?", "EXTRA"],
            "search_keywords": ["celebrity followers", "most followed celebrities 2026"],
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    result = await agent.run(content_contract=content_contract())

    assert len(result["title_variants"]) == 2
    assert len(result["description_variants"]) == 3
    assert len(result["tags"]) == 20
    assert len(result["thumbnail_text_suggestions"]) == 3
    assert result["selected_metadata"]["title"] == "Celebrity Follower Numbers That Feel Unreal"
    assert result["title_variants"][0]["score_total"] > result["title_variants"][1]["score_total"]
