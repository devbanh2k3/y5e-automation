# Autonomous Celebrity Topic Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select, score, reserve, and produce diverse Celebrity topics automatically without near-duplicate videos across a batch or later runs.

**Architecture:** Add a focused topic strategy module and a lock-protected JSON history repository. The batch runner requests a reserved topic slate, passes each topic unchanged through `produce()` and `Pipeline` to `ContentAgent`, then marks reservations produced or failed while retaining the existing image, render, quality, and review pipeline.

**Tech Stack:** Python 3.12+, asyncio, Pydantic settings, standard-library `dataclasses`, `difflib`, `fcntl`, JSON, pytest/pytest-asyncio.

---

## File Structure

- Create `core/topic_history.py`: atomic, inter-process-locked persistence and reservation status transitions.
- Create `agents/topic_strategy_agent.py`: candidate normalization, deterministic validation, similarity, cooldown, AI generation, scoring, diverse selection, and reservation.
- Create `tests/test_topic_history.py`: persistence, transitions, corruption, and concurrent reservation coverage.
- Create `tests/test_topic_strategy_agent.py`: validation, semantic deduplication, cooldown, scoring, expansion, and selection coverage.
- Modify `agents/content_agent.py`: accept a selected topic and skip internal topic generation when supplied.
- Modify `agents/pipeline.py`: accept and return topic strategy metadata during Celebrity local render.
- Modify `scripts/produce_celebrity_video.py`: pass selected topics through the single-video boundary and expose strategy metadata.
- Modify `scripts/batch_produce_celebrity_videos.py`: reserve a slate, produce it, update history, and select one replacement after failure.
- Modify existing tests for each changed public interface.

### Task 1: Topic Candidate Rules And Similarity

**Files:**
- Create: `agents/topic_strategy_agent.py`
- Test: `tests/test_topic_strategy_agent.py`

- [ ] **Step 1: Write failing tests for normalization, validation, and similarity**

```python
from agents.topic_strategy_agent import (
    normalize_candidate,
    topic_similarity,
    validate_candidate,
)


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


def test_validation_accepts_open_taxonomy_but_rejects_unsafe_or_non_person_topics():
    assert validate_candidate(candidate(category="touring_revenue")) == []
    assert "individual people" in " ".join(
        validate_candidate(candidate(entity_type="bands"))
    ).lower()
    assert "unsafe" in " ".join(
        validate_candidate(candidate(title="Celebrity medical diagnosis ranking"))
    ).lower()


def test_similarity_detects_minor_title_variants():
    left = normalize_candidate(candidate())
    right = normalize_candidate(candidate(title="Top 10 Highest Paid Actors Per Movie Role"))
    assert topic_similarity(left, right) >= 0.72
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'agents.topic_strategy_agent'`.

- [ ] **Step 3: Implement candidate normalization, validation, and weighted token similarity**

Create `agents/topic_strategy_agent.py` with:

```python
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

REQUIRED_FIELDS = (
    "title", "category", "angle", "metric_label", "entity_type",
    "data_availability_reason", "image_availability_reason", "viral_reason",
)
UNSAFE_TERMS = {"diagnosis", "medical", "addiction", "affair", "rumor", "criminal"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def normalize_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    result = {key: str(raw.get(key, "")).strip() for key in REQUIRED_FIELDS}
    result["title"] = result["title"].strip()
    result["normalized_title"] = _normalized_text(result["title"])
    result["category"] = _slug(result["category"])
    result["angle"] = _slug(result["angle"])
    result["metric_label"] = result["metric_label"].upper()
    result["entity_type"] = _slug(result["entity_type"])
    result["time_scope"] = _slug(str(raw.get("time_scope", "current")))
    return result


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    errors = [f"{field} is required" for field in REQUIRED_FIELDS if not candidate.get(field)]
    if candidate.get("entity_type") != "individual_people":
        errors.append("entity_type must contain individual people")
    title_tokens = set(str(candidate.get("normalized_title", "")).split())
    if title_tokens & UNSAFE_TERMS:
        errors.append("unsafe or sensitive topic")
    return errors


def topic_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    title_ratio = SequenceMatcher(
        None, str(left["normalized_title"]), str(right["normalized_title"])
    ).ratio()
    same_angle = float(left.get("angle") == right.get("angle"))
    same_metric = float(left.get("metric_label") == right.get("metric_label"))
    return 0.65 * title_ratio + 0.25 * same_angle + 0.10 * same_metric
```

- [ ] **Step 4: Run focused tests**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit candidate rules**

```bash
git add agents/topic_strategy_agent.py tests/test_topic_strategy_agent.py
git commit -m "feat: add celebrity topic candidate rules"
```

### Task 2: Durable Lock-Protected Topic History

**Files:**
- Create: `core/topic_history.py`
- Create: `tests/test_topic_history.py`

- [ ] **Step 1: Write failing repository tests**

```python
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.topic_history import TopicHistoryError, TopicHistoryRepository


def reservation(key="movie_salary"):
    return {
        "reservation_id": key,
        "title": "Top Movie Salaries",
        "normalized_title": "top movie salaries",
        "angle": key,
        "metric_label": "SALARY",
        "status": "reserved",
    }


def test_repository_persists_status_transitions(tmp_path):
    repo = TopicHistoryRepository(tmp_path / "celebrity_topic_history.json")
    repo.reserve_many([reservation()])
    repo.mark_produced("movie_salary", topic_id="123")
    record = repo.load()[0]
    assert record["status"] == "produced"
    assert record["topic_id"] == "123"


def test_repository_refuses_duplicate_reservation_across_threads(tmp_path):
    path = tmp_path / "celebrity_topic_history.json"
    def reserve():
        return TopicHistoryRepository(path).reserve_many([reservation()])
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(bool(value) for value in outcomes) == 1


def test_repository_preserves_corrupt_history(tmp_path):
    path = tmp_path / "celebrity_topic_history.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(TopicHistoryError, match="corrupt"):
        TopicHistoryRepository(path).load()
    assert path.read_text(encoding="utf-8") == "{broken"
```

- [ ] **Step 2: Run tests and confirm the repository is missing**

Run: `python3 -m pytest tests/test_topic_history.py -q`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement locked read-reserve-write and atomic transitions**

Create `core/topic_history.py`. `reserve_many()` must open `<history>.lock`, acquire `fcntl.LOCK_EX`, load current records while holding the lock, reject a reservation when its `reservation_id` or normalized title already exists, append accepted records with UTC timestamps, write a temporary file beside the destination, then call `os.replace()`. Implement `mark_produced()` and `mark_failed()` through the same locked update helper. Raise `TopicHistoryError("topic history is corrupt: ...")` on JSON decode failure without modifying the source file.

Use these public signatures exactly:

```python
class TopicHistoryError(RuntimeError):
    pass


class TopicHistoryRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(f"{path.suffix}.lock")

    def load(self) -> list[dict[str, Any]]:
        return self._locked_read()

    def reserve_many(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._locked_reserve(candidates)

    def mark_produced(self, reservation_id: str, *, topic_id: str) -> dict[str, Any]:
        return self._locked_transition(reservation_id, status="produced", topic_id=topic_id)

    def mark_failed(self, reservation_id: str, *, reason: str) -> dict[str, Any]:
        return self._locked_transition(reservation_id, status="failed", failure_reason=reason)
```

- [ ] **Step 4: Run repository tests repeatedly to exercise locking**

Run: `for i in 1 2 3 4 5; do python3 -m pytest tests/test_topic_history.py -q || exit 1; done`

Expected: all five runs PASS.

- [ ] **Step 5: Commit history repository**

```bash
git add core/topic_history.py tests/test_topic_history.py
git commit -m "feat: persist celebrity topic reservations"
```

### Task 3: AI Candidate Generation, Scoring, Cooldown, And Slate Selection

**Files:**
- Modify: `agents/topic_strategy_agent.py`
- Modify: `tests/test_topic_strategy_agent.py`

- [ ] **Step 1: Add failing strategy tests**

Add tests using a temporary `TopicHistoryRepository` and monkeypatched `agent.ai_json` that prove:

```python
@pytest.mark.asyncio
async def test_strategy_selects_distinct_angles_and_metrics(agent, monkeypatch):
    monkeypatch.setattr(agent, "ai_json", fake_candidate_payload)
    selected = await agent.run(count=3, language="en", batch_id="batch-1")
    assert len(selected) == 3
    assert len({item["angle"] for item in selected}) == 3
    assert len({item["metric_label"] for item in selected}) == 3
    assert all(item["status"] == "reserved" for item in selected)
    assert all(item["score_total"] >= 0 for item in selected)


@pytest.mark.asyncio
async def test_strategy_enforces_ten_video_angle_cooldown(agent, repository, monkeypatch):
    repository.reserve_many(history_records_with_ten_recent_angles("single_movie_salary"))
    monkeypatch.setattr(agent, "ai_json", fake_payload_including_movie_salary)
    selected = await agent.run(count=1, language="en", batch_id="batch-2")
    assert selected[0]["angle"] != "single_movie_salary"


@pytest.mark.asyncio
async def test_strategy_expands_pool_once_when_first_pool_is_not_diverse(agent, monkeypatch):
    monkeypatch.setattr(agent, "ai_json", two_stage_candidate_payload)
    selected = await agent.run(count=2, language="en", batch_id="batch-3")
    assert len(selected) == 2
    assert two_stage_candidate_payload.calls == 2
```

The fixture payloads must include one new category such as `touring_revenue` to prove taxonomy is open after deterministic validation.

- [ ] **Step 2: Run the new tests and confirm missing `TopicStrategyAgent` behavior**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py -q`

Expected: FAIL because `TopicStrategyAgent` and scoring APIs do not exist.

- [ ] **Step 3: Implement the strategy agent**

Add `TopicStrategyAgent(BaseAgent)` with:

```python
class TopicSelectionError(RuntimeError):
    pass


class TopicStrategyAgent(BaseAgent):
    def __init__(self, repository: TopicHistoryRepository | None = None) -> None:
        super().__init__(name="topic_strategy_agent")
        path = get_settings().storage_dir / "celebrity_topic_history.json"
        self.repository = repository or TopicHistoryRepository(path)

    async def run(self, *, count: int, language: str, batch_id: str) -> list[dict[str, Any]]:
        history = self.repository.load()
        candidates = await self._generate_candidates(
            count=max(count * 5, 10), language=language, history=history, expanded=False
        )
        selected = self._select_diverse(candidates, history=history, count=count)
        if len(selected) < count:
            candidates.extend(await self._generate_candidates(
                count=max(count * 5, 10), language=language,
                history=history + candidates, expanded=True,
            ))
            selected = self._select_diverse(candidates, history=history, count=count)
        if len(selected) != count:
            raise TopicSelectionError(f"could not select {count} diverse Celebrity topics")
        reserved = self.repository.reserve_many(
            self._prepare_reservations(selected, batch_id=batch_id)
        )
        if len(reserved) != count:
            raise TopicSelectionError("topic reservations changed concurrently")
        return reserved
```

The AI prompt must request a JSON object with `candidates`, include the candidate contract from the spec, seed taxonomy as examples rather than an allowlist, include the last 30 historical titles/angles, and explicitly demand varied angle and metric combinations.

Calculate deterministic score components from AI-provided integer signals clamped to 0-100:

```python
score_total = round(
    viral_score * 0.30
    + data_score * 0.25
    + novelty_score * 0.25
    + image_score * 0.15
    + safety_score * 0.05,
    2,
)
```

Recompute `novelty_score` as `100 * (1 - max_similarity)` against full history/current selection, cap it at 20 for cooldown violations, and reject similarities `>= 0.72`. Select greedily by total score while requiring unique angles and metrics. Give each candidate a UUID `reservation_id`, `batch_id`, score breakdown, `selection_reason`, and `status="reserved"` before repository reservation.

- [ ] **Step 4: Run strategy and history tests**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py tests/test_topic_history.py -q`

Expected: PASS.

- [ ] **Step 5: Commit autonomous selection**

```bash
git add agents/topic_strategy_agent.py tests/test_topic_strategy_agent.py
git commit -m "feat: select diverse celebrity topic slates"
```

### Task 4: Make ContentAgent Consume The Selected Topic

**Files:**
- Modify: `agents/content_agent.py`
- Modify: `tests/test_content_agent.py`

- [ ] **Step 1: Write a failing explicit-topic test**

```python
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
        return valid_awards_contract_payload()

    monkeypatch.setattr(agent, "ai_json", fake_ai_json)
    contract = await agent.run(
        niche="celebrity", language="en", subject="famous people",
        card_layout="flag_hero", selected_topic=selected,
    )
    assert len(prompts) == 1
    assert "Top 10 Most-Awarded Living Musicians" in prompts[0]
    assert contract["youtube_title"] == "Top 10 Most-Awarded Living Musicians"
```

- [ ] **Step 2: Run the test and confirm the signature rejects `selected_topic`**

Run: `python3 -m pytest tests/test_content_agent.py::test_content_agent_uses_selected_topic_without_regenerating_it -q`

Expected: FAIL with unexpected keyword argument `selected_topic`.

- [ ] **Step 3: Add the explicit topic boundary**

Change `ContentAgent.run()` and `_build_ai_celebrity_contract()` to accept `selected_topic: dict[str, Any] | None = None`. Use `selected_topic` directly when supplied; call `_generate_celebrity_topic()` only when absent. Keep the existing seeded fallback for single-video resilience, but if an explicit selected topic fails contract generation, raise the error instead of silently rendering the fixed net-worth fallback because that would violate the reservation.

- [ ] **Step 4: Run ContentAgent tests**

Run: `python3 -m pytest tests/test_content_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit explicit topic consumption**

```bash
git add agents/content_agent.py tests/test_content_agent.py
git commit -m "feat: build celebrity content from selected topics"
```

### Task 5: Pass Topic Strategy Metadata Through Pipeline And Producer

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `scripts/produce_celebrity_video.py`
- Modify: `tests/test_pipeline_local_render.py`
- Modify: `tests/test_produce_celebrity_video.py`

- [ ] **Step 1: Write failing pass-through tests**

Update the fake `ContentAgent.run()` signature in pipeline tests and assert:

```python
selected_topic = {
    "reservation_id": "reservation-1",
    "title": "Top 10 Most-Awarded Living Musicians",
    "angle": "living_musician_awards",
    "metric_label": "AWARDS",
    "score_total": 91.5,
}
result = await Pipeline().run_local_render(
    category="Celebrity", language="en", card_layout="flag_hero",
    selected_topic=selected_topic,
)
assert captured["selected_topic"] == selected_topic
assert result["selected_topic"] == selected_topic
```

Add a producer test that monkeypatches `Pipeline.run_local_render`, calls `produce(..., selected_topic=selected_topic)`, and asserts the argument and returned `selected_topic` are unchanged.

- [ ] **Step 2: Run focused tests and confirm signature failures**

Run: `python3 -m pytest tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py -q`

Expected: FAIL on unexpected `selected_topic` arguments.

- [ ] **Step 3: Implement pass-through without changing render behavior**

Add `selected_topic: dict[str, Any] | None = None` to `Pipeline.run_local_render()` and `produce()`. Pass it to `ContentAgent.run()` and include it in both result dictionaries. Update all test fakes to accept the new keyword. Do not instantiate `TopicStrategyAgent` inside `Pipeline`; orchestration owns selection.

- [ ] **Step 4: Run focused integration tests**

Run: `python3 -m pytest tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py tests/test_content_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit pipeline pass-through**

```bash
git add agents/pipeline.py scripts/produce_celebrity_video.py tests/test_pipeline_local_render.py tests/test_produce_celebrity_video.py
git commit -m "feat: pass selected celebrity topics into rendering"
```

### Task 6: Orchestrate Reserved Slates In Batch Production

**Files:**
- Modify: `scripts/batch_produce_celebrity_videos.py`
- Modify: `tests/test_batch_produce_celebrity_videos.py`

- [ ] **Step 1: Write failing batch orchestration tests**

Add a fake strategy returning distinct reservations and assert `produce_batch()` passes each selected topic exactly once, calls `mark_produced()` with the resulting topic ID, and includes `title`, `angle`, `metric_label`, `score_total`, score breakdown, and selection reason in each summary item.

Add a failure test where the second production raises: assert it calls `mark_failed(reason=...)`, requests one replacement from the strategy, produces the replacement, and never retries the failed reserved topic. Add an exhaustion test asserting a clear failure entry when no replacement can be selected.

- [ ] **Step 2: Run batch tests and confirm no strategy orchestration exists**

Run: `python3 -m pytest tests/test_batch_produce_celebrity_videos.py -q`

Expected: FAIL because `produce_batch()` does not create or accept a strategy and `produce()` receives no selected topic.

- [ ] **Step 3: Implement batch slate orchestration**

At batch start create a UUID `batch_id`, instantiate `TopicStrategyAgent`, and call:

```python
slate = await strategy.run(count=count, language=language, batch_id=batch_id)
```

For each selected topic call:

```python
result = await produce(
    language=language,
    card_layout=card_layout,
    write_files=write_files,
    selected_topic=selected_topic,
)
```

On success call `strategy.repository.mark_produced(reservation_id, topic_id=str(result["topic_id"]))`. On failure call `mark_failed(reservation_id, reason=str(exc))`; unless `stop_on_error`, request one new topic with a replacement batch suffix and process it until the requested success count is met or one replacement per failed slot is exhausted. Ensure `attempted_count` counts actual production attempts and `requested_count` remains the target number of successful videos.

Add `batch_id` and `topic_strategy` to the JSON summary. Keep existing CLI arguments unchanged.

- [ ] **Step 4: Run batch and all strategy tests**

Run: `python3 -m pytest tests/test_batch_produce_celebrity_videos.py tests/test_topic_strategy_agent.py tests/test_topic_history.py -q`

Expected: PASS.

- [ ] **Step 5: Run the complete suite and CLI help verification**

Run: `python3 -m pytest -q`

Expected: all tests PASS.

Run: `python3 scripts/batch_produce_celebrity_videos.py --help`

Expected: exit 0 and existing `--count`, `--language`, `--card-layout`, `--stop-on-error`, and `--no-write-artifacts` options remain documented.

- [ ] **Step 6: Commit batch integration**

```bash
git add scripts/batch_produce_celebrity_videos.py tests/test_batch_produce_celebrity_videos.py
git commit -m "feat: produce diverse reserved celebrity topics"
```

### Task 7: Production Acceptance Verification

**Files:**
- Modify only if verification reveals a defect in files already covered above.

- [ ] **Step 1: Verify clean static and test state**

Run:

```bash
git diff --check
python3 -m pytest -q
```

Expected: no whitespace errors and all tests PASS.

- [ ] **Step 2: Run a no-render strategy probe**

Run a small Python command that constructs `TopicStrategyAgent`, requests three English topics with a unique probe batch ID, and prints title, angle, metric, and score. Do not invoke `produce()` in this probe.

Expected: three reserved topics with distinct angles and metrics. Mark these probe reservations failed with reason `strategy_probe_only` afterward so history remains truthful.

- [ ] **Step 3: Inspect durable history**

Run: `python3 -m json.tool output/celebrity_topic_history.json >/dev/null`

Expected: exit 0. Probe records are present with status `failed`; no duplicate reservation IDs exist.

- [ ] **Step 4: Record final status**

Run: `git status --short --branch`

Expected: clean branch after any required final fix commit.

The next real acceptance command remains:

```bash
python3 scripts/batch_produce_celebrity_videos.py --count 3 --language en --card-layout flag_hero
```

Its summary must show three different topic angles and metrics before the videos are reviewed.
