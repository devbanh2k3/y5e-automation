# Resilient Card Production Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production pipeline that plans globally unique celebrity subjects, recovers malformed AI output, repairs or replaces individual failed cards, and renders when at least 90% of the requested cards are valid.

**Architecture:** Add a shared safe JSON AI boundary and a focused celebrity production orchestrator beside the existing `ContentAgent`. The orchestrator owns candidate planning, locked subject assignment, card states, reserve replacement, minimum-card policy, and checkpoints; the existing fact, image, render, review, and upload components remain the execution backends.

**Tech Stack:** Python 3.11, asyncio, Pydantic settings, httpx, pytest/pytest-asyncio, JSON filesystem checkpoints, existing Remotion/FFmpeg render pipeline, Docker Compose, Telegram bot.

---

## File Structure

- Create `core/ai_resilience.py`: bounded retry classification, tolerant JSON extraction, and structured safe-call results.
- Create `core/card_production.py`: candidate/card models, state transitions, minimum-card policy, deduplication, reserve allocation, and reconciliation helpers.
- Create `core/production_checkpoints.py`: atomic production manifest persistence and resume loading.
- Create `agents/celebrity_content_orchestrator.py`: entity planner, locked-subject scene writer, local repair/replacement loop, and final content contract assembly.
- Modify `agents/content_agent.py`: expose metadata normalization/building helpers and delegate long celebrity production to the orchestrator behind a setting.
- Modify `agents/ai_fact_verification_agent.py`: verify selected card subsets without invalidating sibling cards.
- Modify `agents/real_image_agent.py`: expose one-card verification and return missing items without raising at orchestration time.
- Modify `agents/pipeline.py`: run card-level fact/image recovery before render and report degraded production details.
- Modify `core/config.py` and `.env.example`: bounded resilience and rollout settings.
- Modify `scripts/process_production_task.py`: user-facing progress/result reporting and terminal error sanitization.
- Test in focused new test modules plus existing pipeline/agent tests.

### Task 1: Shared Safe JSON AI Boundary

**Files:**
- Create: `core/ai_resilience.py`
- Create: `tests/test_ai_resilience.py`
- Modify: `core/ai_client.py`

- [ ] **Step 1: Write failing parser and retry tests**

```python
import httpx
import pytest

from core.ai_resilience import AIJsonFailure, safe_generate_json


@pytest.mark.asyncio
async def test_safe_generate_json_keeps_valid_items_from_fenced_json():
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        return 'Result:\n```json\n{"items":[{"name":"Adele"}]}\n```'

    result = await safe_generate_json(generate, prompt="plan", system="json")

    assert result.value == {"items": [{"name": "Adele"}]}
    assert result.attempts == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_safe_generate_json_repairs_malformed_json_once():
    responses = iter(['{"items":[{"name":"Adele",}]}', '{"items":[{"name":"Adele"}]}'])

    async def generate(**kwargs):
        return next(responses)

    result = await safe_generate_json(generate, prompt="plan", system="json", json_repair_attempts=1)

    assert result.value["items"][0]["name"] == "Adele"
    assert result.json_repairs == 1


@pytest.mark.asyncio
async def test_safe_generate_json_returns_structured_failure_after_budget():
    async def generate(**kwargs):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AIJsonFailure) as exc_info:
        await safe_generate_json(generate, prompt="plan", system="json", transport_attempts=2)

    assert exc_info.value.category == "transport_exhausted"
    assert exc_info.value.attempts == 2
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `pytest tests/test_ai_resilience.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'core.ai_resilience'`.

- [ ] **Step 3: Implement structured safe JSON calls**

```python
# core/ai_resilience.py
from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx


@dataclass(frozen=True)
class AIJsonResult:
    value: dict[str, Any]
    attempts: int
    json_repairs: int


class AIJsonFailure(RuntimeError):
    def __init__(self, message: str, *, category: str, attempts: int) -> None:
        super().__init__(message)
        self.category = category
        self.attempts = attempts


def extract_json_object(raw: str) -> dict[str, Any]:
    candidates = [raw.strip()]
    fenced = re.search(r"```(?:json)?\\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    braced = re.search(r"\{.*\}", raw, re.DOTALL)
    if braced:
        candidates.append(braced.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("AI response does not contain a JSON object")


async def safe_generate_json(
    generate: Callable[..., Awaitable[str]],
    *,
    prompt: str,
    system: str,
    transport_attempts: int = 3,
    json_repair_attempts: int = 2,
) -> AIJsonResult:
    attempts = 0
    repairs = 0
    current_prompt = prompt
    while attempts < transport_attempts:
        attempts += 1
        try:
            raw = await generate(prompt=current_prompt, system=system, response_format={"type": "json_object"})
            try:
                return AIJsonResult(extract_json_object(raw), attempts, repairs)
            except ValueError as exc:
                if repairs >= json_repair_attempts:
                    raise AIJsonFailure(str(exc), category="json_exhausted", attempts=attempts) from exc
                repairs += 1
                current_prompt = "Return corrected JSON only for this malformed response:\n" + raw
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempts >= transport_attempts:
                raise AIJsonFailure(str(exc), category="transport_exhausted", attempts=attempts) from exc
            await asyncio.sleep(min(4.0, (2 ** (attempts - 1)) + random.random()))
    raise AIJsonFailure("AI retry budget exhausted", category="transport_exhausted", attempts=attempts)
```

Refactor `core.ai_client.generate_json()` to call `generate()` plus `extract_json_object()` so existing callers gain tolerant fenced/prose extraction without changing their signatures. Keep endpoint fallback behavior in `generate()`.

- [ ] **Step 4: Run focused and existing AI client tests**

Run: `pytest tests/test_ai_resilience.py tests/test_ai_client_docker_url.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ai_resilience.py core/ai_client.py tests/test_ai_resilience.py
git commit -m "feat: add resilient AI JSON boundary"
```

### Task 2: Card Production Domain and Minimum Gate

**Files:**
- Create: `core/card_production.py`
- Create: `tests/test_card_production.py`

- [ ] **Step 1: Write failing domain tests**

```python
from core.card_production import Candidate, CardRecord, CardState, ProductionInventory


def test_candidate_pool_deduplicates_normalized_names_and_aliases():
    inventory = ProductionInventory(target_cards=4, format_minimum_cards=2, minimum_ratio=0.90)
    inventory.add_candidates([
        Candidate("Beyonce", "US", aliases=("Beyoncé",)),
        Candidate("Beyoncé", "US"),
        Candidate("Adele", "GB"),
    ])
    assert [item.name for item in inventory.candidates] == ["Beyonce", "Adele"]


def test_failed_card_consumes_unique_reserve_then_can_be_skipped():
    inventory = ProductionInventory(target_cards=2, format_minimum_cards=1, minimum_ratio=0.50)
    inventory.lock_candidates([
        Candidate("Adele", "GB"),
        Candidate("Rihanna", "BB"),
        Candidate("Pink", "US"),
    ])
    replacement = inventory.replace("card-1", reason="image_missing")
    assert replacement.candidate.name == "Pink"
    assert inventory.cards["card-1"].state is CardState.REPLACING


def test_minimum_gate_accepts_90_percent_and_reindexes_ranking():
    inventory = ProductionInventory(target_cards=10, format_minimum_cards=6, minimum_ratio=0.90)
    inventory.cards = {
        f"card-{index}": CardRecord.ready(f"card-{index}", name=f"Person {index}")
        for index in range(9)
    }
    scenes = inventory.finalize_scenes(content_format="ranking")
    assert inventory.can_render is True
    assert [scene["title"].split()[0] for scene in scenes] == [f"#{rank}" for rank in range(9, 0, -1)]
```

- [ ] **Step 2: Run test and verify failure**

Run: `pytest tests/test_card_production.py -q`

Expected: FAIL during collection because `core.card_production` does not exist.

- [ ] **Step 3: Implement bounded states and inventory rules**

Implement these public interfaces in `core/card_production.py`:

```python
class CardState(str, Enum):
    PLANNED = "planned"
    CONTENT_GENERATING = "content_generating"
    CONTENT_READY = "content_ready"
    FACT_CHECKING = "fact_checking"
    FACT_READY = "fact_ready"
    IMAGE_SEARCHING = "image_searching"
    READY = "ready"
    REPAIRING = "repairing"
    REPLACING = "replacing"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class Candidate:
    name: str
    country_code: str
    selection_reason: str = ""
    aliases: tuple[str, ...] = ()


@dataclass
class CardRecord:
    card_id: str
    candidate: Candidate
    state: CardState = CardState.PLANNED
    attempts: dict[str, int] = field(default_factory=dict)
    scene: dict[str, Any] | None = None
    last_error: str = ""
    replacement_names: list[str] = field(default_factory=list)


@dataclass
class ProductionInventory:
    target_cards: int
    format_minimum_cards: int
    minimum_ratio: float = 0.90
    candidates: list[Candidate] = field(default_factory=list)
    cards: dict[str, CardRecord] = field(default_factory=dict)
    reserve: deque[Candidate] = field(default_factory=deque)

    @property
    def minimum_cards(self) -> int:
        return max(self.format_minimum_cards, math.ceil(self.target_cards * self.minimum_ratio))

    @property
    def can_render(self) -> bool:
        return sum(card.state is CardState.READY for card in self.cards.values()) >= self.minimum_cards
```

Add `normalize_person_key`, `add_candidates`, `lock_candidates`, `replace`, `skip`, and `finalize_scenes`. `replace` must pop atomically from one deque; `finalize_scenes` must exclude skipped/failed cards and apply contiguous ranking only after filtering.

- [ ] **Step 4: Run domain tests**

Run: `pytest tests/test_card_production.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/card_production.py tests/test_card_production.py
git commit -m "feat: add resilient card inventory model"
```

### Task 3: Atomic Checkpoints and Resume

**Files:**
- Create: `core/production_checkpoints.py`
- Create: `tests/test_production_checkpoints.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing checkpoint tests**

```python
from core.production_checkpoints import CheckpointStore


def test_checkpoint_round_trip_preserves_ready_cards(tmp_path):
    store = CheckpointStore(tmp_path, run_id="run-1")
    store.save("card-states", {"card-1": {"state": "ready"}})
    assert store.load("card-states") == {"card-1": {"state": "ready"}}
    assert not list(store.run_dir.glob("*.tmp"))


def test_checkpoint_ignores_uncommitted_temp_file(tmp_path):
    store = CheckpointStore(tmp_path, run_id="run-1")
    store.run_dir.mkdir(parents=True)
    (store.run_dir / "scenes.json.tmp").write_text('{"broken":')
    assert store.load("scenes", default={}) == {}
```

- [ ] **Step 2: Run test and verify missing module**

Run: `pytest tests/test_production_checkpoints.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement atomic JSON persistence**

```python
class CheckpointStore:
    def __init__(self, storage_dir: Path, *, run_id: str) -> None:
        self.run_dir = storage_dir / "production_runs" / run_id

    def save(self, name: str, payload: Any) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        destination = self.run_dir / f"{name}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load(self, name: str, *, default: Any = None) -> Any:
        path = self.run_dir / f"{name}.json"
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def append_error(self, payload: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

Add serialization helpers on the inventory domain so card state can be reconstructed. Exclude `output/production_runs/` only when the configured storage root is inside the repository; production volumes remain unaffected.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_production_checkpoints.py tests/test_card_production.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/production_checkpoints.py core/card_production.py tests/test_production_checkpoints.py tests/test_card_production.py .gitignore
git commit -m "feat: checkpoint card production runs"
```

### Task 4: Entity Planner and Locked Scene Writer

**Files:**
- Create: `agents/celebrity_content_orchestrator.py`
- Create: `tests/test_celebrity_content_orchestrator.py`
- Modify: `agents/content_agent.py`

- [ ] **Step 1: Write failing planner/writer tests**

```python
@pytest.mark.asyncio
async def test_planner_locks_unique_people_before_scene_chunks(monkeypatch):
    orchestrator = CelebrityContentOrchestrator()
    planner_responses = iter([
        {"candidates": [candidate("Adele"), candidate("Adele"), candidate("Rihanna")]},
        {"candidates": [candidate("Pink"), candidate("Beyonce")]},
    ])
    written_subjects = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return next(planner_responses)
        written_subjects.extend(kwargs["locked_names"])
        return {"scenes": [scene(name) for name in kwargs["locked_names"]]}

    monkeypatch.setattr(orchestrator, "_call_json", fake_json)
    result = await orchestrator.build(topic=topic(), target_cards=3, metadata_contract=metadata())

    assert written_subjects == ["Adele", "Rihanna", "Pink"]
    assert len({normalize_person_key(item["title"]) for item in result["scenes"]}) == 3


@pytest.mark.asyncio
async def test_writer_keeps_valid_partial_chunk_and_requests_only_missing_subject(monkeypatch):
    orchestrator = CelebrityContentOrchestrator()
    writer_requests = []

    async def fake_json(*, operation, **kwargs):
        if operation == "entity_plan":
            return {"candidates": [candidate("Adele"), candidate("Rihanna"), candidate("Pink"), candidate("Beyonce")]}
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
assert [scene["title"] for scene in result["scenes"]] == ["Adele", "Rihanna", "Pink"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_celebrity_content_orchestrator.py -q`

Expected: FAIL because the orchestrator does not exist.

- [ ] **Step 3: Implement candidate planning and locked writing**

Create `CelebrityContentOrchestrator` with these boundaries:

```python
class CelebrityContentOrchestrator(BaseAgent):
    async def build(
        self,
        *,
        topic: dict[str, Any],
        target_cards: int,
        metadata_contract: dict[str, Any],
        language: str,
        subject: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        inventory = ProductionInventory(
            target_cards=target_cards,
            format_minimum_cards=6,
            minimum_ratio=get_settings().card_minimum_ratio,
        )
        candidates = await self._plan_candidates(
            target_cards=target_cards,
            blacklist=set(),
            topic=topic,
        )
        inventory.add_candidates(candidates)
        inventory.lock_candidates(inventory.candidates)
        scene_map = await self._write_locked_scenes(
            candidates=[card.candidate for card in inventory.cards.values()],
            topic=topic,
            metadata_contract=metadata_contract,
        )
        for card in inventory.cards.values():
            scene = scene_map.get(normalize_person_key(card.candidate.name))
            if scene is not None:
                card.scene = scene
                card.state = CardState.CONTENT_READY
        return {
            **metadata_contract,
            "scenes": [card.scene for card in inventory.cards.values() if card.scene],
            "inventory": inventory,
        }

    async def _plan_candidates(
        self,
        *,
        target_cards: int,
        blacklist: set[str],
        topic: dict[str, Any],
    ) -> list[Candidate]:
        requested = target_cards + max(10, math.ceil(target_cards * 0.25))
        accepted: list[Candidate] = []
        rejected_keys = set(blacklist)
        for _attempt in range(get_settings().card_planner_attempts):
            missing = requested - len(accepted)
            if missing <= 0:
                break
            payload = await self._call_json(
                operation="entity_plan",
                topic=topic,
                requested_count=missing,
                blacklist=sorted(rejected_keys | {normalize_person_key(item.name) for item in accepted}),
            )
            for raw in payload.get("candidates", []):
                candidate = Candidate.from_dict(raw)
                key = normalize_person_key(candidate.name)
                if key and key not in rejected_keys and all(normalize_person_key(item.name) != key for item in accepted):
                    accepted.append(candidate)
        return accepted

    async def _write_locked_scenes(
        self,
        *,
        candidates: list[Candidate],
        topic: dict[str, Any],
        metadata_contract: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        pending = {normalize_person_key(item.name): item for item in candidates}
        scenes: dict[str, dict[str, Any]] = {}
        for _attempt in range(get_settings().card_content_repair_attempts + 1):
            if not pending:
                break
            for candidate_chunk in batched(list(pending.values()), 12):
                locked_names = [item.name for item in candidate_chunk]
                payload = await self._call_json(
                    operation="scene_write",
                    topic=topic,
                    metadata_contract=metadata_contract,
                    locked_names=locked_names,
                )
                for scene in payload.get("scenes", []):
                    key = normalize_person_key(extract_scene_person_name(scene))
                    if key in pending and validate_scene_shape(scene):
                        scenes[key] = scene
                        pending.pop(key)
        return scenes
```

Use `requested_candidates = target_cards + max(10, ceil(target_cards * 0.25))`. Keep accepted partial planner output, refill only the deficit, and stop after the configured planner budget. Chunk locked candidates in groups of 12. Reconcile scenes by normalized person identity and retry only missing/invalid subjects.

Move person-name normalization and group rejection from `ContentAgent` into `core.card_production`, then import those helpers from both modules. Keep the existing metadata prompt and `_normalize_ai_celebrity_contract` behavior until Task 7.

- [ ] **Step 4: Run orchestrator and existing content tests**

Run: `pytest tests/test_celebrity_content_orchestrator.py tests/test_content_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/celebrity_content_orchestrator.py agents/content_agent.py core/card_production.py tests/test_celebrity_content_orchestrator.py tests/test_content_agent.py
git commit -m "feat: plan locked celebrity subjects before writing"
```

### Task 5: Card-Level Fact and Image Verification

**Files:**
- Modify: `agents/ai_fact_verification_agent.py`
- Modify: `agents/real_image_agent.py`
- Modify: `tests/test_ai_fact_verification_agent.py`
- Modify: `tests/test_real_image_agent.py`

- [ ] **Step 1: Write failing subset verification tests**

```python
@pytest.mark.asyncio
async def test_fact_agent_returns_results_per_scene_without_rejecting_siblings(monkeypatch):
    agent = AIFactVerificationAgent()
    monkeypatch.setattr(agent, "ai_json", AsyncMock(return_value={"items": [
        verified_item(0, "Adele"),
        rejected_item(1, "Rihanna"),
    ]}))
    results = await agent.verify_scenes(content_contract=contract_with_two_scenes())
    assert results[0]["status"] == "verified"
    assert results[1]["status"] == "rejected"


@pytest.mark.asyncio
async def test_real_image_agent_can_verify_one_scene_without_strict_batch_failure(monkeypatch):
    agent = RealImageAgent()
    monkeypatch.setattr(agent, "_find_verified_image", AsyncMock(return_value=None))
    item = await agent.verify_scene(topic_id=1, scene_index=0, scene=scene("Adele"))
    assert item["status"] == "missing"
```

- [ ] **Step 2: Run focused tests and confirm missing methods**

Run: `pytest tests/test_ai_fact_verification_agent.py tests/test_real_image_agent.py -q`

Expected: FAIL because `verify_scenes` and `verify_scene` are not public yet.

- [ ] **Step 3: Add non-throwing card-level APIs**

Refactor `AIFactVerificationAgent.run()` to call:

```python
async def verify_scenes(self, *, content_contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized verification items; rejected cards remain data, not exceptions."""

def build_verified_contract(self, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the strict final contract after the orchestrator removes rejected cards."""
```

Expose on `RealImageAgent`:

```python
async def verify_scene(self, *, topic_id: int, scene_index: int, scene: dict[str, Any]) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(1)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        return await self._verify_scene_image(
            client=client,
            semaphore=semaphore,
            topic_id=topic_id,
            scene_index=scene_index,
            scene=scene,
        )
```

Keep existing strict batch APIs backward compatible.

- [ ] **Step 4: Run agent tests**

Run: `pytest tests/test_ai_fact_verification_agent.py tests/test_real_image_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/ai_fact_verification_agent.py agents/real_image_agent.py tests/test_ai_fact_verification_agent.py tests/test_real_image_agent.py
git commit -m "feat: verify celebrity cards independently"
```

### Task 6: Repair, Replace, and Skip Orchestration

**Files:**
- Modify: `agents/celebrity_content_orchestrator.py`
- Modify: `core/card_production.py`
- Modify: `tests/test_celebrity_content_orchestrator.py`

- [ ] **Step 1: Write failing local recovery tests**

```python
@pytest.mark.asyncio
async def test_low_confidence_card_is_replaced_without_rewriting_ready_cards(monkeypatch):
    orchestrator = prepared_orchestrator(primary=["Adele", "Rihanna"], reserve=["Pink"])
    writer = AsyncMock(side_effect=[scenes_for("Adele", "Rihanna"), scenes_for("Pink")])
    verifier = AsyncMock(side_effect=[verified("Adele"), rejected("Rihanna"), verified("Pink")])
    orchestrator.write_scenes = writer
    orchestrator.verify_fact = verifier

    result = await orchestrator.recover_cards()

    assert writer.await_args_list[1].kwargs["locked_names"] == ["Pink"]
    assert [item["title"] for item in result.ready_scenes] == ["Adele", "Pink"]


@pytest.mark.asyncio
async def test_two_hard_cards_can_be_skipped_when_minimum_gate_still_passes():
    orchestrator = prepared_orchestrator(target=20, ready=18, failed=2, minimum_ratio=0.90)
    result = await orchestrator.finalize()
    assert result.degraded is True
    assert result.final_card_count == 18


@pytest.mark.asyncio
async def test_run_fails_only_below_minimum_after_reserve_exhaustion():
    orchestrator = prepared_orchestrator(target=20, ready=17, failed=3, reserve=[])
    with pytest.raises(InsufficientReadyCardsError):
        await orchestrator.finalize()
```

- [ ] **Step 2: Run tests and confirm recovery behavior is absent**

Run: `pytest tests/test_celebrity_content_orchestrator.py -q`

Expected: FAIL on missing recovery methods/results.

- [ ] **Step 3: Implement stage-local recovery**

Add bounded loops that use these defaults:

```python
CONTENT_REPAIR_ATTEMPTS = 2
FACT_REPAIR_ATTEMPTS = 2
REPLACEMENTS_PER_SLOT = 3

async def recover_card(self, card: CardRecord) -> CardRecord:
    for stage in (self._ensure_content, self._ensure_fact, self._ensure_image):
        try:
            card = await stage(card)
        except RecoverableCardError as exc:
            card.last_error = exc.category
            replacement = self.inventory.replace(card.card_id, reason=exc.category)
            return await self.recover_card(replacement)
    card.state = CardState.READY
    self.checkpoints.save("card-states", self.inventory.to_dict())
    return card
```

Implement the loop iteratively rather than recursively if replacement depth would obscure attempt accounting. Catch exceptions at each card boundary, classify them, append sanitized diagnostics, and continue processing sibling cards. Use `asyncio.gather(..., return_exceptions=True)` only where results are reconciled explicitly.

Before final output, skip exhausted cards, call `finalize_scenes`, update actual count in title/hook/metadata fields where a numeric count exists, and rebuild strict fact/image contracts from ready cards only.

- [ ] **Step 4: Run recovery and contract tests**

Run: `pytest tests/test_celebrity_content_orchestrator.py tests/test_multiformat_video_contract.py tests/test_fact_verification.py tests/test_image_verification_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/celebrity_content_orchestrator.py core/card_production.py tests/test_celebrity_content_orchestrator.py
git commit -m "feat: repair or replace failed celebrity cards"
```

### Task 7: Pipeline Integration and Feature Flag

**Files:**
- Modify: `core/config.py`
- Modify: `.env.example`
- Modify: `agents/content_agent.py`
- Modify: `agents/pipeline.py`
- Modify: `scripts/produce_celebrity_video.py`
- Modify: `tests/test_config_validation.py`
- Modify: `tests/test_content_agent.py`
- Modify: `tests/test_pipeline_local_render.py`
- Modify: `tests/test_produce_celebrity_video.py`

- [ ] **Step 1: Write failing integration tests**

```python
@pytest.mark.asyncio
async def test_pipeline_uses_resilient_orchestrator_and_renders_degraded_result(monkeypatch):
    monkeypatch.setenv("RESILIENT_CARD_PIPELINE_ENABLED", "true")
    monkeypatch.setattr(
        CelebrityContentOrchestrator,
        "build",
        AsyncMock(return_value=orchestrated_result(target=20, final=18)),
    )
    result = await Pipeline().run_local_render(
        category="Celebrity", language="en", duration_target=108
    )
    assert result["production_summary"]["target_cards"] == 20
    assert result["production_summary"]["final_cards"] == 18
    assert result["production_summary"]["degraded"] is True


def test_resilience_settings_are_bounded(monkeypatch):
    monkeypatch.setenv("CARD_MINIMUM_RATIO", "1.5")
    assert get_settings().card_minimum_ratio == 1.0


def test_single_video_cli_accepts_target_duration():
    args = build_parser().parse_args(["--target-duration", "180"])
    assert args.target_duration == 180
```

- [ ] **Step 2: Run tests and verify missing configuration/integration**

Run: `pytest tests/test_config_validation.py tests/test_content_agent.py tests/test_pipeline_local_render.py -q`

Expected: FAIL on missing resilient pipeline settings and summary.

- [ ] **Step 3: Add settings and integrate without changing render contracts**

Add settings with validators/bounded properties:

```python
resilient_card_pipeline_enabled: bool = True
card_minimum_ratio: float = 0.90
card_content_repair_attempts: int = 2
card_fact_repair_attempts: int = 2
card_replacement_attempts: int = 3
ai_json_repair_attempts: int = 2
ai_transport_attempts: int = 3
```

Document matching variables in `.env.example`. In `ContentAgent`, retain short non-celebrity and seeded fallback behavior, but delegate AI celebrity scene production to `CelebrityContentOrchestrator` when enabled. In `Pipeline.run_local_render`, consume the orchestrator's final content/fact/image contracts directly and avoid running whole-contract strict verification a second time.

Return:

```python
"production_summary": {
    "target_cards": target_cards,
    "minimum_cards": minimum_cards,
    "final_cards": len(content_contract["scenes"]),
    "repaired_cards": repaired_count,
    "replaced_cards": replaced_count,
    "skipped_cards": skipped_count,
    "degraded": len(content_contract["scenes"]) < target_cards,
}
```

Keep `validate_video_data`, quality gate, thumbnail, render, review, and upload flow unchanged.

Add `--target-duration` to `scripts/produce_celebrity_video.py`, validate it with the same production duration bounds as the batch command, and pass it to `produce()`.

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/test_config_validation.py tests/test_content_agent.py tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py tests/test_quality_gate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/config.py .env.example agents/content_agent.py agents/pipeline.py scripts/produce_celebrity_video.py tests/test_config_validation.py tests/test_content_agent.py tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py
git commit -m "feat: integrate resilient celebrity production"
```

### Task 8: Telegram Reporting and Controlled Worker Failures

**Files:**
- Modify: `agents/celebrity_content_orchestrator.py`
- Modify: `agents/pipeline.py`
- Modify: `scripts/produce_celebrity_video.py`
- Modify: `scripts/process_production_task.py`
- Modify: `services/telegram_remote.py`
- Modify: `tests/test_celebrity_content_orchestrator.py`
- Modify: `tests/test_pipeline_local_render.py`
- Modify: `tests/test_produce_celebrity_video.py`
- Modify: `tests/test_process_production_task.py`
- Modify: `tests/test_telegram_remote.py`

- [ ] **Step 1: Write failing user-facing message tests**

```python
def test_completion_message_reports_degraded_card_counts_without_internal_ids():
    text = build_production_completion_message(
        title="Celebrity Records",
        layout="flag_hero",
        target_duration=180,
        summary={"target_cards": 58, "final_cards": 55, "skipped_cards": 3, "degraded": True},
    )
    assert "55/58 card" in text
    assert "3 card" in text
    assert "task_id" not in text


def test_failure_message_maps_internal_exception_to_actionable_text():
    text = build_production_failure_message(AIJsonFailure("raw payload", category="json_exhausted", attempts=3))
    assert "AI trả dữ liệu không hợp lệ" in text
    assert "raw payload" not in text


@pytest.mark.asyncio
async def test_worker_progress_callback_reports_counts_without_blocking_production(monkeypatch):
    sent = []

    async def fake_notify(**kwargs):
        sent.append(kwargs["text"])
        return True

    monkeypatch.setattr(worker, "_notify_owner", fake_notify)
    callback = worker.build_progress_callback(owner_telegram_user_id=42)
    await callback({"stage": "image_verification", "ready": 43, "target": 54, "repairing": 2})
    assert sent == ["Đang xác minh hình ảnh: 43/54 card\nĐang sửa: 2"]
```

- [ ] **Step 2: Run tests and verify message builders are missing**

Run: `pytest tests/test_process_production_task.py tests/test_telegram_remote.py -q`

Expected: FAIL on missing builders.

- [ ] **Step 3: Implement professional summaries**

Add pure builders and use them from `process_one_task()`. Map categories to stable Vietnamese explanations:

```python
FAILURE_LABELS = {
    "transport_exhausted": "Không thể kết nối dịch vụ AI sau nhiều lần thử.",
    "json_exhausted": "AI trả dữ liệu không hợp lệ sau nhiều lần tự sửa.",
    "insufficient_ready_cards": "Không đủ card có dữ liệu và hình ảnh đáng tin cậy để render.",
    "render_failed": "Hệ thống render video không hoàn tất.",
}
```

Keep full exception context in structured logs. Telegram receives the mapped label, `/status` instruction, and final/target counts when available. Never include checkpoint paths, UUIDs, stack traces, or raw AI responses.

Thread an optional async `progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None` through `produce()`, `Pipeline.run_local_render()`, and `CelebrityContentOrchestrator.build()`. Emit events after planning, content reconciliation, fact verification, image verification, and finalization. The worker callback is best-effort: notification exceptions are logged and never change card or run state. Rate-limit Telegram progress updates to a stage change or at least 15 seconds since the previous message.

- [ ] **Step 4: Run worker and Telegram tests**

Run: `pytest tests/test_celebrity_content_orchestrator.py tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py tests/test_process_production_task.py tests/test_telegram_remote.py tests/test_telegram_notifications.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/celebrity_content_orchestrator.py agents/pipeline.py scripts/produce_celebrity_video.py scripts/process_production_task.py services/telegram_remote.py tests/test_celebrity_content_orchestrator.py tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py tests/test_process_production_task.py tests/test_telegram_remote.py
git commit -m "feat: report resilient production outcomes"
```

### Task 9: Full Verification, Docker Smoke, and Rollout

**Files:**
- Modify: `docs/PRODUCTION_RUNBOOK.md` if present, otherwise modify the repository's existing production runbook discovered by `rg -n "Production Runbook" docs`.
- Modify: `.env.example`
- Test: all `tests/`

- [ ] **Step 1: Run formatting/static repository checks**

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 2: Run the complete test suite**

Run: `pytest -q`

Expected: all tests pass with no failures.

- [ ] **Step 3: Rebuild only affected Docker services**

Run: `docker compose build api worker telegram-bot`

Expected: all three images build successfully.

- [ ] **Step 4: Restart and verify service health**

Run: `docker compose up -d api worker telegram-bot`

Run: `docker compose ps`

Expected: `api`, `worker`, and `telegram-bot` are running; health-enabled services report healthy.

- [ ] **Step 5: Run focused production smoke**

Run: `python3 scripts/produce_celebrity_video.py --language en --card-layout flag_hero --target-duration 180`

Expected: one MP4 reaches `pending_review`; `production_summary.final_cards >= production_summary.minimum_cards`; no duplicate celebrity appears; review artifacts include final fact/image contracts and checkpoint summary.

- [ ] **Step 6: Verify controlled degradation with injected test fixtures**

Run: `pytest tests/test_celebrity_content_orchestrator.py -q -k "skip or replace or malformed or resume"`

Expected: PASS and demonstrate malformed JSON recovery, local replacement, legal skip, and below-minimum terminal failure.

- [ ] **Step 7: Update runbook**

Document these operational controls and meanings:

```dotenv
RESILIENT_CARD_PIPELINE_ENABLED=true
CARD_MINIMUM_RATIO=0.90
CARD_CONTENT_REPAIR_ATTEMPTS=2
CARD_FACT_REPAIR_ATTEMPTS=2
CARD_REPLACEMENT_ATTEMPTS=3
AI_JSON_REPAIR_ATTEMPTS=2
AI_TRANSPORT_ATTEMPTS=3
```

Include checkpoint location, resume behavior, degraded completion meaning, and the rule that reducing `CARD_MINIMUM_RATIO` trades factual coverage for completion rate.

- [ ] **Step 8: Commit verification documentation**

```bash
git add .env.example docs
git commit -m "docs: document resilient production operations"
```

- [ ] **Step 9: Inspect final history and working tree**

Run: `git status --short && git log --oneline -10`

Expected: clean working tree and one focused commit per completed task.
