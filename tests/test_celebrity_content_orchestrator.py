import pytest

from agents.celebrity_content_orchestrator import CelebrityContentOrchestrator
from core.card_production import normalize_person_key


def candidate(name: str, country_code: str = "US") -> dict:
    return {"name": name, "countryCode": country_code, "selectionReason": "fit"}


def scene(name: str) -> dict:
    return {
        "title": name,
        "voiceover": f"Fact about {name}",
        "caption": "100",
        "image_prompt": f"real editorial photo of {name}",
        "statusText": "FACT | 100",
        "countryCode": "US",
        "countryLabel": "UNITED STATES",
        "metricLabel": "AWARDS",
        "metricValue": "100",
        "factClaim": f"{name} has 100 awards",
        "factValue": "100",
        "factUnit": "awards",
        "factAsOf": "2025",
        "factContext": "career total",
        "sourceRequirement": "public awards database",
    }


def topic() -> dict:
    return {
        "title": "Celebrity award records",
        "content_format": "non_ranking",
        "metric_label": "AWARDS",
    }


def metadata() -> dict:
    return {"title": "Celebrity award records", "scenes": []}


@pytest.mark.asyncio
async def test_planner_locks_unique_people_before_scene_chunks(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0,
        minimum_reserve=0,
        planner_attempts=2,
    )
    planner_responses = iter(
        [
            {
                "candidates": [
                    candidate("Adele", "GB"),
                    candidate("Adele", "GB"),
                    candidate("Rihanna", "BB"),
                ]
            },
            {"candidates": [candidate("Pink"), candidate("Beyonce")]},
        ]
    )
    written_subjects = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return next(planner_responses)
        written_subjects.extend(kwargs["locked_names"])
        return {"scenes": [scene(name) for name in kwargs["locked_names"]]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(
        topic=topic(),
        target_cards=3,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
    )

    assert written_subjects == ["Adele", "Rihanna", "Pink"]
    assert len({normalize_person_key(item["title"]) for item in result["scenes"]}) == 3


@pytest.mark.asyncio
async def test_writer_keeps_valid_partial_chunk_and_requests_only_missing_subject(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0,
        minimum_reserve=0,
        planner_attempts=1,
        content_attempts=2,
    )
    writer_requests = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return {
                "candidates": [
                    candidate("Adele", "GB"),
                    candidate("Rihanna", "BB"),
                    candidate("Pink"),
                ]
            }
        writer_requests.append(kwargs["locked_names"])
        if len(writer_requests) == 1:
            return {"scenes": [scene("Adele"), scene("Rihanna")]}
        return {"scenes": [scene("Pink")]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(
        topic=topic(),
        target_cards=3,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
    )

    assert writer_requests == [["Adele", "Rihanna", "Pink"], ["Pink"]]
    assert [item["title"] for item in result["scenes"]] == [
        "Adele",
        "Rihanna",
        "Pink",
    ]


@pytest.mark.asyncio
async def test_planner_rejects_unsupported_country_code_and_refills(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0,
        minimum_reserve=0,
        planner_attempts=2,
    )
    responses = iter(
        [
            {"candidates": [candidate("Adele", "ZZ")]},
            {"candidates": [candidate("Rihanna", "BB")]},
        ]
    )

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return next(responses)
        return {"scenes": [scene(name) for name in kwargs["locked_names"]]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(
        topic=topic(),
        target_cards=1,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
    )

    assert [item["title"] for item in result["scenes"]] == ["Rihanna"]
