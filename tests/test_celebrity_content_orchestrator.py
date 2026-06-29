import pytest

from agents.celebrity_content_orchestrator import CelebrityContentOrchestrator
from core.card_production import (
    Candidate,
    CardRecord,
    CardState,
    InsufficientReadyCardsError,
    ProductionInventory,
    normalize_person_key,
)


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
    return {
        "title": "Celebrity award records",
        "contentFormat": "non_ranking",
        "scenes": [],
    }


def fact_item(name: str, *, status: str = "verified") -> dict:
    return {
        "scene_index": 0,
        "person_name": name,
        "metric_label": "AWARDS",
        "original_value": "100",
        "verified_value": "100",
        "unit": "awards",
        "as_of": "2025",
        "status": status,
        "confidence": 0.95 if status != "rejected" else 0.2,
        "reason": "public record",
        "knowledge_cutoff_risk": "low",
    }


def image_item(name: str, *, status: str = "verified") -> dict:
    base = {
        "scene_index": 0,
        "person_name": name,
        "expected_title": name,
        "status": status,
        "confidence": 0.95 if status == "verified" else 0.0,
        "reject_reason": "" if status == "verified" else "not found",
    }
    if status == "verified":
        base.update(
            {
                "local_path": f"/tmp/{name}.webp",
                "render_image_path": f"images/{name}.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                "image_url": "https://upload.wikimedia.org/example.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Example",
            }
        )
    return base


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
async def test_build_replaces_content_missing_cards_from_reserve_before_failing(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0.5,
        minimum_reserve=2,
        planner_attempts=1,
        content_attempts=1,
        replacement_attempts=2,
        minimum_ratio=0.75,
    )
    writer_requests = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return {
                "candidates": [
                    candidate("Adele", "GB"),
                    candidate("Rihanna", "BB"),
                    candidate("Pink"),
                    candidate("Beyonce"),
                    candidate("Taylor Swift"),
                    candidate("Lady Gaga"),
                ]
            }
        writer_requests.append(kwargs["locked_names"])
        return {
            "scenes": [
                scene(name)
                for name in kwargs["locked_names"]
                if name in {"Adele", "Rihanna", "Taylor Swift", "Lady Gaga"}
            ]
        }

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(
        topic=topic(),
        target_cards=4,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
    )

    assert writer_requests == [
        ["Adele", "Rihanna", "Pink", "Beyonce"],
        ["Taylor Swift", "Lady Gaga"],
    ]
    assert [item["title"] for item in result["scenes"]] == [
        "Adele",
        "Rihanna",
        "Taylor Swift",
        "Lady Gaga",
    ]


@pytest.mark.asyncio
async def test_scene_writer_uses_locked_candidate_country_metadata(monkeypatch):
    orchestrator = CelebrityContentOrchestrator()

    async def fake_json(*, operation, **kwargs):
        bad_scene = scene("Adele")
        bad_scene["countryCode"] = "ZZ"
        bad_scene["countryLabel"] = "UNKNOWN"
        return {"scenes": [bad_scene]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    scenes = await orchestrator._write_locked_scenes(
        candidates=[Candidate("Adele", "GB")],
        topic=topic(),
        metadata_contract=metadata(),
        language="en",
    )

    assert scenes["adele"]["countryCode"] == "GB"
    assert scenes["adele"]["countryLabel"] == "UNITED KINGDOM"


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


@pytest.mark.asyncio
async def test_orchestrator_emits_stage_progress_without_exposing_card_ids(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0,
        minimum_reserve=0,
        planner_attempts=1,
    )
    events = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return {"candidates": [candidate("Adele", "GB")]}
        return {"scenes": [scene("Adele")]}

    async def progress(event):
        events.append(event)

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    await orchestrator.build(
        topic=topic(),
        target_cards=1,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
        progress_callback=progress,
    )

    assert [event["stage"] for event in events] == [
        "entity_planning",
        "content_writing",
    ]
    assert all("card_id" not in event for event in events)


@pytest.mark.asyncio
async def test_build_resumes_ready_content_from_checkpoint_without_new_ai_calls(
    monkeypatch,
    tmp_path,
):
    first = CelebrityContentOrchestrator(
        reserve_ratio=0,
        minimum_reserve=0,
        planner_attempts=1,
        storage_dir=tmp_path,
    )

    async def first_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return {"candidates": [candidate("Adele", "GB")]}
        return {"scenes": [scene("Adele")]}

    monkeypatch.setattr(first, "_call_json", first_json)
    await first.build(
        topic=topic(),
        target_cards=1,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
        run_id="run-1",
    )

    resumed = CelebrityContentOrchestrator(storage_dir=tmp_path)

    async def unexpected_json(**kwargs):
        raise AssertionError("checkpointed content must not call AI again")

    monkeypatch.setattr(resumed, "_call_json", unexpected_json)
    result = await resumed.build(
        topic=topic(),
        target_cards=1,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
        run_id="run-1",
    )

    assert [item["title"] for item in result["scenes"]] == ["Adele"]


@pytest.mark.asyncio
async def test_build_resumes_partial_checkpoint_and_writes_only_missing_subject(
    monkeypatch,
    tmp_path,
):
    from core.production_checkpoints import CheckpointStore

    inventory = ProductionInventory(2, 1, 0.50)
    inventory.add_candidates([Candidate("Adele", "GB"), Candidate("Pink", "US")])
    inventory.lock_candidates(inventory.candidates)
    first, second = inventory.cards.values()
    first.scene = scene("Adele")
    first.state = CardState.CONTENT_READY
    CheckpointStore(tmp_path, run_id="run-2").save("card-states", inventory.to_dict())
    orchestrator = CelebrityContentOrchestrator(storage_dir=tmp_path)
    requests = []

    async def fake_json(*, operation, **kwargs):
        assert operation == "scene_write"
        requests.append(kwargs["locked_names"])
        return {"scenes": [scene("Pink")]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(
        topic=topic(),
        target_cards=2,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
        run_id="run-2",
    )

    assert requests == [["Pink"]]
    assert [item["title"] for item in result["scenes"]] == ["Adele", "Pink"]


@pytest.mark.asyncio
async def test_ai_retry_budgets_are_forwarded_to_safe_json_call(monkeypatch):
    from core.ai_resilience import AIJsonResult

    captured = {}
    orchestrator = CelebrityContentOrchestrator(
        ai_transport_attempts=5,
        ai_json_repair_attempts=4,
    )

    async def fake_safe_generate_json(generate, **kwargs):
        captured.update(kwargs)
        return AIJsonResult(value={"candidates": []}, attempts=1, json_repairs=0)

    monkeypatch.setattr(
        "agents.celebrity_content_orchestrator.safe_generate_json",
        fake_safe_generate_json,
    )

    await orchestrator._call_json(
        operation="entity_plan",
        topic=topic(),
        language="en",
        subject="celebrity",
        requested_count=1,
        blacklist=[],
    )

    assert captured["transport_attempts"] == 5
    assert captured["json_repair_attempts"] == 4


@pytest.mark.asyncio
async def test_rejected_fact_replaces_only_failed_card(monkeypatch):
    orchestrator = CelebrityContentOrchestrator(
        reserve_ratio=0.5,
        minimum_reserve=1,
        planner_attempts=1,
        fact_attempts=1,
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
        return {"scenes": [scene(name) for name in kwargs["locked_names"]]}

    class FactAgent:
        async def verify_scenes(self, *, content_contract):
            name = content_contract["scenes"][0]["title"]
            return [fact_item(name, status="rejected" if name == "Rihanna" else "verified")]

        def build_verified_contract(self, items):
            from core.fact_verification import build_fact_verification_contract_v1

            return build_fact_verification_contract_v1(items)

    class ImageAgent:
        async def verify_scene(self, *, topic_id, scene_index, scene):
            return image_item(scene["title"])

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    planned = await orchestrator.build(
        topic=topic(),
        target_cards=2,
        metadata_contract=metadata(),
        language="en",
        subject="celebrity",
    )
    result = await orchestrator.verify_and_recover(
        planned,
        topic_id=1,
        topic=topic(),
        language="en",
        fact_agent=FactAgent(),
        image_agent=ImageAgent(),
    )

    assert writer_requests == [["Adele", "Rihanna"], ["Pink"]]
    assert [item["title"] for item in result["content_contract"]["scenes"]] == [
        "Adele",
        "Pink",
    ]
    assert result["production_summary"]["replaced_cards"] == 1


@pytest.mark.asyncio
async def test_hard_card_is_skipped_when_ninety_percent_are_ready():
    orchestrator = CelebrityContentOrchestrator(minimum_reserve=0, fact_attempts=1)
    inventory = ProductionInventory(10, 6, 0.90)
    for index in range(10):
        name = f"Person {index}"
        inventory.cards[f"card-{index}"] = CardRecord(
            card_id=f"card-{index}",
            candidate=Candidate(name, "US"),
            state=CardState.CONTENT_READY,
            scene=scene(name),
        )
    planned = {**metadata(), "scenes": [card.scene for card in inventory.cards.values()], "inventory": inventory}

    class FactAgent:
        async def verify_scenes(self, *, content_contract):
            name = content_contract["scenes"][0]["title"]
            item = fact_item(name)
            if name == "Person 0":
                item["verified_value"] = "101"
            return [item]

        def build_verified_contract(self, items):
            from core.fact_verification import build_fact_verification_contract_v1

            return build_fact_verification_contract_v1(items)

    class ImageAgent:
        async def verify_scene(self, *, topic_id, scene_index, scene):
            status = "missing_image" if scene["title"] == "Person 9" else "verified"
            return image_item(scene["title"], status=status)

    result = await orchestrator.verify_and_recover(
        planned,
        topic_id=1,
        topic=topic(),
        language="en",
        fact_agent=FactAgent(),
        image_agent=ImageAgent(),
    )

    assert result["production_summary"]["final_cards"] == 9
    assert result["production_summary"]["skipped_cards"] == 1
    assert result["production_summary"]["degraded"] is True
    assert result["content_contract"]["scenes"][0]["metricValue"] == "101"
    assert result["content_contract"]["scenes"][0]["factValue"] == "101"
    assert result["image_verification_contract"]["items"][0]["render_image_path"] == "images/real_0.webp"
    assert result["image_verification_contract"]["items"][1]["render_image_path"] == "images/real_1.webp"


@pytest.mark.asyncio
async def test_run_fails_only_after_ready_cards_remain_below_minimum():
    orchestrator = CelebrityContentOrchestrator(minimum_reserve=0, fact_attempts=1)
    inventory = ProductionInventory(10, 6, 0.90)
    for index in range(10):
        name = f"Person {index}"
        inventory.cards[f"card-{index}"] = CardRecord(
            card_id=f"card-{index}",
            candidate=Candidate(name, "US"),
            state=CardState.CONTENT_READY,
            scene=scene(name),
        )
    planned = {**metadata(), "scenes": [card.scene for card in inventory.cards.values()], "inventory": inventory}

    class FactAgent:
        async def verify_scenes(self, *, content_contract):
            name = content_contract["scenes"][0]["title"]
            return [fact_item(name)]

        def build_verified_contract(self, items):
            from core.fact_verification import build_fact_verification_contract_v1

            return build_fact_verification_contract_v1(items)

    class ImageAgent:
        async def verify_scene(self, *, topic_id, scene_index, scene):
            missing = scene["title"] in {"Person 8", "Person 9"}
            return image_item(scene["title"], status="missing_image" if missing else "verified")

    with pytest.raises(InsufficientReadyCardsError):
        await orchestrator.verify_and_recover(
            planned,
            topic_id=1,
            topic=topic(),
            language="en",
            fact_agent=FactAgent(),
            image_agent=ImageAgent(),
        )


@pytest.mark.asyncio
async def test_recovery_does_not_reverify_checkpointed_ready_card():
    orchestrator = CelebrityContentOrchestrator(minimum_reserve=0)
    inventory = ProductionInventory(2, 1, 0.50)
    inventory.lock_candidates([Candidate("Adele", "GB"), Candidate("Pink", "US")])
    first, second = inventory.cards.values()
    first.scene = scene("Adele")
    first.fact_item = fact_item("Adele")
    first.image_item = image_item("Adele")
    first.state = CardState.READY
    second.scene = scene("Pink")
    second.state = CardState.CONTENT_READY
    planned = {**metadata(), "scenes": [first.scene, second.scene], "inventory": inventory}
    verified_names = []

    class FactAgent:
        async def verify_scenes(self, *, content_contract):
            name = content_contract["scenes"][0]["title"]
            verified_names.append(name)
            return [fact_item(name)]

        def build_verified_contract(self, items):
            from core.fact_verification import build_fact_verification_contract_v1

            return build_fact_verification_contract_v1(items)

    class ImageAgent:
        async def verify_scene(self, *, topic_id, scene_index, scene):
            return image_item(scene["title"])

    await orchestrator.verify_and_recover(
        planned,
        topic_id=1,
        topic=topic(),
        language="en",
        fact_agent=FactAgent(),
        image_agent=ImageAgent(),
    )

    assert verified_names == ["Pink"]
