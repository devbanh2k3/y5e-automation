import json

import pytest

from agents.topic_strategy_agent import TopicStrategyAgent
from agents.topic_strategy_agent import (
    normalize_candidate,
    topic_similarity,
    validate_candidate,
)
from core.topic_history import TopicHistoryRepository


def candidate(**overrides):
    value = {
        "title": "Top 10 Highest-Paid Movie Roles",
        "category": "film",
        "angle": "single_movie_salary",
        "metric_label": "SALARY",
        "entity_type": "individual_people",
        "data_availability_reason": "Public trade reporting exists",
        "image_availability_reason": "Editorial portraits exist",
        "viral_reason": "Recognizable names and money",
        "time_scope": "all_time",
    }
    value.update(overrides)
    return value


def test_normalize_candidate_uses_stable_keys():
    result = normalize_candidate(candidate(title="  Top 10 HIGHest Paid Movie Roles! "))

    assert result["normalized_title"] == "top 10 highest paid movie roles"
    assert result["angle"] == "single_movie_salary"
    assert result["metric_label"] == "SALARY"


def test_normalize_candidate_accepts_ai_scores_on_zero_to_ten_scale():
    result = normalize_candidate(candidate(viral_score=9, data_score=10))

    assert result["viral_score"] == 90
    assert result["data_score"] == 100


def test_validation_accepts_open_taxonomy_but_rejects_unsafe_or_non_person_topics():
    open_taxonomy = normalize_candidate(candidate(category="touring_revenue"))
    non_person = normalize_candidate(candidate(entity_type="bands"))
    unsafe = normalize_candidate(candidate(title="Celebrity medical diagnosis ranking"))

    assert validate_candidate(open_taxonomy) == []
    assert "individual people" in " ".join(validate_candidate(non_person)).lower()
    assert "unsafe" in " ".join(validate_candidate(unsafe)).lower()


def test_similarity_detects_minor_title_variants():
    left = normalize_candidate(candidate())
    right = normalize_candidate(
        candidate(title="Top 10 Highest Paid Actors Per Movie Role")
    )

    assert topic_similarity(left, right) >= 0.72


def scored_candidate(title, category, angle, metric, score=90):
    return candidate(
        title=title,
        category=category,
        angle=angle,
        metric_label=metric,
        viral_score=score,
        data_score=score,
        image_score=score,
        safety_score=score,
    )


@pytest.fixture
def repository(tmp_path):
    return TopicHistoryRepository(tmp_path / "celebrity_topic_history.json")


@pytest.fixture
def agent(repository):
    return TopicStrategyAgent(repository=repository)


@pytest.mark.asyncio
async def test_strategy_selects_distinct_angles_and_metrics(agent, monkeypatch):
    async def fake_ai_json(prompt, system=None, **kwargs):
        return {
            "candidates": [
                scored_candidate(
                    "Top 10 Celebrity Touring Revenues",
                    "touring_revenue",
                    "tour_income",
                    "TOUR REVENUE",
                    94,
                ),
                scored_candidate(
                    "Top 10 Most-Awarded Living Musicians",
                    "music",
                    "living_music_awards",
                    "AWARDS",
                    92,
                ),
                scored_candidate(
                    "Top 10 Longest Celebrity Careers",
                    "career",
                    "career_longevity",
                    "YEARS",
                    90,
                ),
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    selected = await agent.run(count=3, language="en", batch_id="batch-1")

    assert len(selected) == 3
    assert len({item["angle"] for item in selected}) == 3
    assert len({item["metric_label"] for item in selected}) == 3
    assert all(item["status"] == "reserved" for item in selected)
    assert all(item["score_total"] >= 0 for item in selected)


@pytest.mark.asyncio
async def test_strategy_enforces_ten_video_angle_cooldown(
    agent,
    repository,
    monkeypatch,
):
    history = []
    for index in range(10):
        item = normalize_candidate(
            scored_candidate(
                f"Historical topic {index}",
                "film",
                "single_movie_salary" if index == 9 else f"angle_{index}",
                f"METRIC {index}",
            )
        )
        item.update(reservation_id=f"history-{index}", status="reserved")
        history.append(item)
    repository.reserve_many(history)

    async def fake_ai_json(prompt, system=None, **kwargs):
        return {
            "candidates": [
                scored_candidate(
                    "Top 10 Highest-Paid Movie Roles",
                    "film",
                    "single_movie_salary",
                    "SALARY",
                    99,
                ),
                scored_candidate(
                    "Top 10 Most Followed Athletes",
                    "sports",
                    "athlete_followers",
                    "FOLLOWERS",
                    85,
                ),
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    selected = await agent.run(count=1, language="en", batch_id="batch-2")

    assert selected[0]["angle"] == "athlete_followers"


@pytest.mark.asyncio
async def test_strategy_expands_pool_once_when_first_pool_is_not_diverse(
    agent,
    monkeypatch,
):
    calls = 0

    async def fake_ai_json(prompt, system=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "candidates": [
                    scored_candidate(
                        "Top Celebrity Movie Salaries",
                        "film",
                        "movie_salary",
                        "SALARY",
                    ),
                    scored_candidate(
                        "Highest Actor Paychecks Per Film",
                        "film",
                        "movie_salary",
                        "SALARY",
                    ),
                ]
            }
        return {
            "candidates": [
                scored_candidate(
                    "Top Celebrity Movie Salaries",
                    "film",
                    "movie_salary",
                    "SALARY",
                ),
                scored_candidate(
                    "Longest Careers in Pop Music",
                    "career",
                    "music_career_longevity",
                    "YEARS",
                ),
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    selected = await agent.run(count=2, language="en", batch_id="batch-3")

    assert len(selected) == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_strategy_excludes_near_duplicate_legacy_content_contract(
    agent,
    repository,
    monkeypatch,
):
    contract_dir = repository.path.parent / "topics" / "legacy-1"
    contract_dir.mkdir(parents=True)
    (contract_dir / "content_contract.json").write_text(
        json.dumps(
            {
                "youtube_title": "Top 10 Highest-Paid Movie Roles of All Time",
                "scenes": [{"metricLabel": "USD EARNINGS"}],
            }
        ),
        encoding="utf-8",
    )

    async def fake_ai_json(prompt, system=None, **kwargs):
        return {
            "candidates": [
                scored_candidate(
                    "Top 10 Highest-Paid Actors per Movie Role",
                    "film",
                    "single_movie_salary",
                    "USD EARNINGS",
                    99,
                ),
                scored_candidate(
                    "Top 10 Celebrity Touring Revenues",
                    "touring_revenue",
                    "tour_income",
                    "TOUR REVENUE",
                    88,
                ),
            ]
        }

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)

    selected = await agent.run(count=1, language="en", batch_id="legacy-batch")

    assert selected[0]["angle"] == "tour_income"
