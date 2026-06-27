# Batch Production v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production batch runner that fills the requested number of reviewable Celebrity videos with bounded retries, replacements, failure classification, and duration controls.

**Architecture:** Keep production orchestration in `scripts/batch_produce_celebrity_videos.py` and keep single-video production in `scripts/produce_celebrity_video.py`. Duration settings pass through `produce()` into `Pipeline.run_local_render()` and `ContentAgent.run()`, then into the content contract. Batch v2 uses small pure helpers for duration resolution, exception classification, and summary construction so behavior is testable without AI, image, or render calls.

**Tech Stack:** Python 3.14, asyncio, pytest/pytest-asyncio, existing JSON contracts, existing TopicStrategyAgent, ContentAgent, Pipeline, and CLI scripts.

---

## File Structure

- Modify `scripts/batch_produce_celebrity_videos.py`: add duration CLI, failure classification, bounded attempt loop, retry/replacement policy, and richer summary.
- Modify `scripts/produce_celebrity_video.py`: accept and report `duration_profile` and `target_duration`; pass duration target into the pipeline.
- Modify `agents/pipeline.py`: accept `duration_target` in `run_local_render()` and pass it to `ContentAgent.run()`.
- Modify `agents/content_agent.py`: accept optional `duration_target`, pass it into seeded and AI Celebrity contract creation, and include it as `duration_target`.
- Modify `tests/test_batch_produce_celebrity_videos.py`: cover classification, max attempts, retry/replacement policy, duration forwarding, and CLI parsing.
- Modify `tests/test_produce_celebrity_video.py`: cover duration forwarding from `produce()` to `Pipeline.run_local_render()`.
- Modify `tests/test_pipeline_local_render.py`: cover duration forwarding from pipeline to ContentAgent.
- Modify `tests/test_content_agent.py`: cover selected-topic AI contracts preserve explicit duration target.

### Task 1: Duration Profile And Pass-Through Contract

**Files:**
- Modify: `scripts/batch_produce_celebrity_videos.py`
- Modify: `scripts/produce_celebrity_video.py`
- Modify: `agents/pipeline.py`
- Modify: `agents/content_agent.py`
- Modify: `tests/test_batch_produce_celebrity_videos.py`
- Modify: `tests/test_produce_celebrity_video.py`
- Modify: `tests/test_pipeline_local_render.py`
- Modify: `tests/test_content_agent.py`

- [ ] **Step 1: Write failing duration profile tests in batch script**

Add to `tests/test_batch_produce_celebrity_videos.py`:

```python
def test_resolve_duration_target_uses_profile_defaults():
    from scripts.batch_produce_celebrity_videos import resolve_duration_target

    assert resolve_duration_target("short", None) == 40
    assert resolve_duration_target("standard", None) == 60
    assert resolve_duration_target("long", None) == 90


def test_resolve_duration_target_allows_explicit_override():
    from scripts.batch_produce_celebrity_videos import resolve_duration_target

    assert resolve_duration_target("standard", 75) == 75
```

- [ ] **Step 2: Write failing duration forwarding tests**

Add to `tests/test_produce_celebrity_video.py`:

```python
@pytest.mark.asyncio
async def test_produce_passes_duration_target_to_pipeline(monkeypatch):
    from scripts import produce_celebrity_video as producer

    captured = {}

    async def fake_run_local_render(
        self,
        *,
        category,
        language,
        card_layout,
        selected_topic,
        duration_target,
    ):
        captured["duration_target"] = duration_target
        return {
            "review_status": "pending_review",
            "review_id": "review-1",
            "topic_id": 123,
            "file_path": "/tmp/final_video.mp4",
            "duration_sec": 62,
            "quality_gate": {"status": "passed"},
            "youtube_title": "Title",
            "selected_topic": selected_topic,
        }

    async def fake_get_review(review_id):
        return {"review_id": review_id}

    monkeypatch.setattr(producer.Pipeline, "run_local_render", fake_run_local_render)
    monkeypatch.setattr(producer, "get_review", fake_get_review)

    result = await producer.produce(
        language="en",
        card_layout="flag_hero",
        write_files=False,
        selected_topic={"title": "Topic"},
        duration_profile="standard",
        target_duration=60,
    )

    assert captured["duration_target"] == 60
    assert result["duration_profile"] == "standard"
    assert result["target_duration"] == 60
    assert result["actual_duration_sec"] == 62
```

Add to `tests/test_pipeline_local_render.py`:

```python
@pytest.mark.asyncio
async def test_run_local_render_passes_duration_target_to_content_agent(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    captured = {}

    class FakeContentAgent:
        async def run(self, **kwargs):
            captured["duration_target"] = kwargs["duration_target"]
            return build_content_contract_v2(
                niche="celebrity",
                title="Duration Test",
                hook="Hook",
                target_audience="Fans",
                language="en",
                scenes=[
                    {
                        "title": "#1 Taylor Swift",
                        "voiceover": "Taylor Swift has a public estimate.",
                        "caption": "1.6B USD",
                        "image_prompt": "real editorial photo of Taylor Swift",
                        "statusText": "#1 | 1.6B USD",
                        "countryCode": "US",
                        "countryLabel": "UNITED STATES",
                        "metricLabel": "NET WORTH",
                        "metricValue": "1.6B USD",
                    }
                ],
                thumbnail_prompt="thumbnail",
                youtube_title="Duration Test",
                youtube_description="Description",
                youtube_tags=["celebrity"],
                duration_target=kwargs["duration_target"],
                cardLayout="flag_hero",
            )

    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": 1,
                "verified_count": 1,
                "status": "verified",
                "items": [
                    {
                        "scene_index": 0,
                        "person_name": "Taylor Swift",
                        "expected_title": "#1 Taylor Swift",
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": "/tmp/real_0.webp",
                        "render_image_path": "images/real_0.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
                        "license": "CC BY-SA 4.0",
                        "attribution": "Example photographer",
                        "quality_score": 0.82,
                        "quality_reason": "portrait metadata",
                        "identity_confidence": 0.95,
                        "content_match_status": "passed",
                        "needs_human_review": False,
                        "source_adapter": "test",
                        "reject_reason": "",
                    }
                ],
            }

    async def fake_render(self, *, topic_id, video_data):
        output = tmp_path / "topics" / str(topic_id) / "final_video.mp4"
        image_dir = output.parent / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "real_0.webp").write_bytes(b"image")
        output.write_bytes(b"fake mp4")
        return {"video_id": 1, "file_path": str(output), "duration_sec": 60, "status": "rendered"}

    async def fake_create_review(**kwargs):
        return {"review_id": "review-1", "status": "pending_review"}

    monkeypatch.setattr("agents.content_agent.ContentAgent", FakeContentAgent)
    monkeypatch.setattr("agents.pipeline.RealImageAgent", FakeRealImageAgent)
    monkeypatch.setattr("agents.pipeline.create_review", fake_create_review)
    monkeypatch.setattr(Pipeline, "_render_local_video", fake_render)

    result = await Pipeline().run_local_render(
        category="Celebrity",
        language="en",
        card_layout="flag_hero",
        duration_target=75,
    )

    assert captured["duration_target"] == 75
    assert result["content_contract"]["duration_target"] == 75
```

Add to `tests/test_content_agent.py`:

```python
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
```

- [ ] **Step 3: Run duration tests and verify RED**

Run:

```bash
python3 -m pytest \
  tests/test_batch_produce_celebrity_videos.py::test_resolve_duration_target_uses_profile_defaults \
  tests/test_batch_produce_celebrity_videos.py::test_resolve_duration_target_allows_explicit_override \
  tests/test_produce_celebrity_video.py::test_produce_passes_duration_target_to_pipeline \
  tests/test_pipeline_local_render.py::test_run_local_render_passes_duration_target_to_content_agent \
  tests/test_content_agent.py::test_content_agent_uses_explicit_duration_target -q
```

Expected: FAIL because duration helpers and pass-through parameters do not exist.

- [ ] **Step 4: Implement minimal duration pass-through**

In `scripts/batch_produce_celebrity_videos.py`, add:

```python
DURATION_PROFILE_TARGETS = {
    "short": 40,
    "standard": 60,
    "long": 90,
}


def resolve_duration_target(duration_profile: str, target_duration: int | None) -> int:
    if target_duration is not None:
        if target_duration < 15:
            raise ValueError("--target-duration must be at least 15 seconds")
        return target_duration
    return DURATION_PROFILE_TARGETS[duration_profile]
```

In `scripts/produce_celebrity_video.py`, update `produce()` signature:

```python
async def produce(
    *,
    language: str,
    card_layout: str = "flag_hero",
    write_files: bool = True,
    selected_topic: dict[str, Any] | None = None,
    duration_profile: str = "standard",
    target_duration: int = 60,
) -> dict[str, Any]:
```

Pass `duration_target=target_duration` into `Pipeline().run_local_render()` and include:

```python
"duration_profile": duration_profile,
"target_duration": target_duration,
"actual_duration_sec": result.get("duration_sec", 0),
```

In `agents/pipeline.py`, add `duration_target: int = 60` to `run_local_render()` and pass it to `ContentAgent().run(..., duration_target=duration_target)`.

In `agents/content_agent.py`, add `duration_target: int = 60` to `run()` and thread it into `_generate_celebrity_contract_from_topic()` and `_seeded_celebrity_contract()`. Use `duration_target=duration_target` when building `build_content_contract_v2()`.

- [ ] **Step 5: Run duration tests and verify GREEN**

Run the same command from Step 3.

Expected: PASS.

- [ ] **Step 6: Commit duration pass-through**

```bash
git add scripts/batch_produce_celebrity_videos.py scripts/produce_celebrity_video.py agents/pipeline.py agents/content_agent.py tests/test_batch_produce_celebrity_videos.py tests/test_produce_celebrity_video.py tests/test_pipeline_local_render.py tests/test_content_agent.py
git commit -m "feat: add batch duration controls"
```

### Task 2: Failure Classification Helpers

**Files:**
- Modify: `scripts/batch_produce_celebrity_videos.py`
- Modify: `tests/test_batch_produce_celebrity_videos.py`

- [ ] **Step 1: Write failing classification tests**

Add to `tests/test_batch_produce_celebrity_videos.py`:

```python
from core.fact_verification import FactVerificationError
from core.video_contract import VideoContractError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (VideoContractError("scenes[0].factClaim is required"), "repairable_contract"),
        (VideoContractError("scenes[8].countryCode is not supported"), "repairable_contract"),
        (FactVerificationError("all facts must be AI verified with confidence >= 0.80"), "fact_rejected"),
        (RuntimeError("image verification failed: wrong person"), "image_failed"),
        (RuntimeError("remotion render failed with exit code 1"), "render_failed"),
        (TopicSelectionError("could not select diverse topics"), "topic_selection_failed"),
        (RuntimeError("anything else"), "unknown"),
    ],
)
def test_classify_batch_failure(exc, expected):
    from scripts.batch_produce_celebrity_videos import classify_batch_failure

    assert classify_batch_failure(exc) == expected
```

- [ ] **Step 2: Run classification test and verify RED**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py::test_classify_batch_failure -q
```

Expected: FAIL because `classify_batch_failure()` does not exist.

- [ ] **Step 3: Implement classification helpers**

In `scripts/batch_produce_celebrity_videos.py`, add imports:

```python
from core.fact_verification import FactVerificationError
from core.video_contract import VideoContractError
```

Add:

```python
def classify_batch_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if isinstance(exc, TopicSelectionError):
        return "topic_selection_failed"
    if isinstance(exc, FactVerificationError):
        return "fact_rejected"
    if isinstance(exc, VideoContractError):
        if any(marker in message for marker in ("factclaim", "factvalue", "factunit", "factasof", "factcontext", "countrycode", "is required")):
            return "repairable_contract"
        return "unknown"
    if "image" in message or "photo" in message or "wikimedia" in message:
        return "image_failed"
    if "render" in message or "remotion" in message or "ffmpeg" in message:
        return "render_failed"
    return "unknown"
```

Add:

```python
def recovery_action_for(classification: str, *, retry_available: bool, stop_on_error: bool) -> str:
    if stop_on_error:
        return "stop_on_error"
    if classification in {"repairable_contract", "render_failed"} and retry_available:
        return "retry_same_topic"
    if classification == "topic_selection_failed":
        return "no_replacement_available"
    return "request_replacement"
```

- [ ] **Step 4: Run classification tests and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py::test_classify_batch_failure -q
```

Expected: PASS.

- [ ] **Step 5: Commit classification helpers**

```bash
git add scripts/batch_produce_celebrity_videos.py tests/test_batch_produce_celebrity_videos.py
git commit -m "feat: classify batch production failures"
```

### Task 3: Bounded Attempts, Retries, Replacements, And Summary v2

**Files:**
- Modify: `scripts/batch_produce_celebrity_videos.py`
- Modify: `tests/test_batch_produce_celebrity_videos.py`

- [ ] **Step 1: Write failing bounded production tests**

Add to `tests/test_batch_produce_celebrity_videos.py`:

```python
@pytest.mark.asyncio
async def test_produce_batch_v2_fills_requested_count_with_replacements(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    failed = selected_topic(1)
    second = selected_topic(2)
    replacement = selected_topic(3)
    strategy = FakeStrategy([[failed, second], [replacement]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
        attempts.append(selected_topic["reservation_id"])
        if selected_topic["reservation_id"] == "reservation-1":
            raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=4,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["success_count"] == 2
    assert summary["requested_count"] == 2
    assert summary["replacement_count"] == 1
    assert summary["unfilled_count"] == 0
    assert summary["status"] == "completed_with_recoveries"
    assert attempts == ["reservation-1", "reservation-2", "reservation-3"]
    assert summary["failures"][0]["classification"] == "fact_rejected"
    assert summary["failures"][0]["recovery_action"] == "request_replacement"
```

Add:

```python
@pytest.mark.asyncio
async def test_produce_batch_v2_retries_repairable_contract_once(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    topic = selected_topic(1)
    strategy = FakeStrategy([[topic]])
    attempts = []

    async def fake_produce(**kwargs):
        selected_topic = kwargs["selected_topic"]
        attempts.append(selected_topic["reservation_id"])
        if len(attempts) == 1:
            raise VideoContractError("scenes[0].factClaim is required")
        return produced_result(len(attempts), selected_topic)

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=1,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["success_count"] == 1
    assert summary["retry_count"] == 1
    assert summary["replacement_count"] == 0
    assert attempts == ["reservation-1", "reservation-1"]
    assert summary["failures"][0]["classification"] == "repairable_contract"
    assert summary["failures"][0]["recovery_action"] == "retry_same_topic"
```

Add:

```python
@pytest.mark.asyncio
async def test_produce_batch_v2_stops_at_max_attempts(monkeypatch):
    from scripts import batch_produce_celebrity_videos as batch_script

    topics = [selected_topic(index) for index in range(1, 6)]
    strategy = FakeStrategy([[topics[0]], [topics[1]], [topics[2]], [topics[3]]])

    async def fake_produce(**kwargs):
        raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")

    monkeypatch.setattr(batch_script, "produce", fake_produce)

    summary = await batch_script.produce_batch(
        count=2,
        language="en",
        card_layout="flag_hero",
        write_files=True,
        stop_on_error=False,
        strategy=strategy,
        max_attempts=3,
        duration_profile="standard",
        target_duration=60,
    )

    assert summary["attempted_count"] == 3
    assert summary["success_count"] == 0
    assert summary["unfilled_count"] == 2
    assert summary["status"] == "incomplete"
    assert summary["failures"][-1]["recovery_action"] == "attempt_budget_exhausted"
```

- [ ] **Step 2: Run v2 batch tests and verify RED**

Run:

```bash
python3 -m pytest \
  tests/test_batch_produce_celebrity_videos.py::test_produce_batch_v2_fills_requested_count_with_replacements \
  tests/test_batch_produce_celebrity_videos.py::test_produce_batch_v2_retries_repairable_contract_once \
  tests/test_batch_produce_celebrity_videos.py::test_produce_batch_v2_stops_at_max_attempts -q
```

Expected: FAIL because `produce_batch()` does not accept new parameters and loop stops when queue empties rather than filling count under attempt budget.

- [ ] **Step 3: Implement v2 loop and summary fields**

Update `produce_batch()` signature:

```python
async def produce_batch(
    *,
    count: int,
    language: str,
    card_layout: str,
    write_files: bool,
    stop_on_error: bool,
    strategy: TopicStrategyAgent | None = None,
    max_attempts: int | None = None,
    duration_profile: str = "standard",
    target_duration: int | None = None,
) -> dict[str, Any]:
```

Inside, compute:

```python
resolved_target_duration = resolve_duration_target(duration_profile, target_duration)
attempt_budget = max_attempts if max_attempts is not None else count * 3
if attempt_budget < count:
    raise ValueError("--max-attempts must be at least --count")
```

Replace the `while queue:` condition with:

```python
while len(items) < count and attempt_index < attempt_budget and queue:
```

Queue entries should be dicts with topic, retry availability, batch slot, and attempt type:

```python
queue = [
    {
        "topic": selected_topic,
        "retry_available": True,
        "batch_slot": index + 1,
        "attempt_type": "initial",
    }
    for index, selected_topic in enumerate(slate)
]
```

When calling `produce()`, pass:

```python
duration_profile=duration_profile,
target_duration=resolved_target_duration,
```

On failure:

```python
classification = classify_batch_failure(exc)
action = recovery_action_for(
    classification,
    retry_available=attempt["retry_available"],
    stop_on_error=stop_on_error,
)
```

If `action == "retry_same_topic"`, append same topic with `retry_available=False` and `attempt_type="retry_same_topic"`; increment `retry_count`.

If `action == "request_replacement"` and there is budget left, call `topic_strategy.run(count=1, ...)` and append replacement with `attempt_type="replacement"`; increment `replacement_count`.

If there is no remaining attempt budget when replacement is needed, set `recovery_action` to `attempt_budget_exhausted`.

Update return summary:

```python
unfilled_count = max(0, count - len(items))
status = (
    "stopped_on_error" if stopped_on_error
    else "completed" if len(items) == count and not failures
    else "completed_with_recoveries" if len(items) == count
    else "incomplete"
)
```

Include `max_attempts`, `replacement_count`, `retry_count`, `unfilled_count`, `duration_profile`, and `target_duration`.

- [ ] **Step 4: Run v2 batch tests and verify GREEN**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Run existing batch tests**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit v2 loop**

```bash
git add scripts/batch_produce_celebrity_videos.py tests/test_batch_produce_celebrity_videos.py
git commit -m "feat: add bounded batch production recovery"
```

### Task 4: CLI Options And Final Verification

**Files:**
- Modify: `scripts/batch_produce_celebrity_videos.py`
- Modify: `tests/test_batch_produce_celebrity_videos.py`

- [ ] **Step 1: Write failing CLI parser test**

Add to `tests/test_batch_produce_celebrity_videos.py`:

```python
def test_batch_cli_accepts_v2_options():
    from scripts.batch_produce_celebrity_videos import build_parser

    args = build_parser().parse_args(
        [
            "--count",
            "10",
            "--language",
            "en",
            "--card-layout",
            "flag_hero",
            "--max-attempts",
            "30",
            "--duration-profile",
            "long",
            "--target-duration",
            "95",
        ]
    )

    assert args.max_attempts == 30
    assert args.duration_profile == "long"
    assert args.target_duration == 95
```

- [ ] **Step 2: Run CLI parser test and verify RED**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py::test_batch_cli_accepts_v2_options -q
```

Expected: FAIL because parser options do not exist.

- [ ] **Step 3: Implement CLI options**

In `build_parser()`, add:

```python
parser.add_argument(
    "--max-attempts",
    type=int,
    default=None,
    help="Maximum production attempts before leaving the batch incomplete. Defaults to count * 3.",
)
parser.add_argument(
    "--duration-profile",
    choices=sorted(DURATION_PROFILE_TARGETS),
    default="standard",
    help="Target duration profile for generated videos.",
)
parser.add_argument(
    "--target-duration",
    type=int,
    default=None,
    help="Explicit target duration in seconds. Overrides --duration-profile target.",
)
```

Pass `max_attempts=args.max_attempts`, `duration_profile=args.duration_profile`, and `target_duration=args.target_duration` to `produce_batch()` in `main()`.

- [ ] **Step 4: Run CLI parser test and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py::test_batch_cli_accepts_v2_options -q
```

Expected: PASS.

- [ ] **Step 5: Run focused verification**

Run:

```bash
python3 -m pytest tests/test_batch_produce_celebrity_videos.py tests/test_produce_celebrity_video.py tests/test_pipeline_local_render.py tests/test_content_agent.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full Python suite**

Run:

```bash
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit CLI and verification updates**

```bash
git add scripts/batch_produce_celebrity_videos.py tests/test_batch_produce_celebrity_videos.py
git commit -m "feat: expose batch production v2 cli"
```

### Task 5: Final Branch Review

**Files:**
- No source changes unless verification exposes a bug.

- [ ] **Step 1: Check branch status**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on `codex/batch-production-v2`.

- [ ] **Step 2: Review commit list**

Run:

```bash
git log --oneline -n 8
```

Expected: includes spec commit plus implementation commits.

- [ ] **Step 3: Report next command for a real batch**

Use this command after merge:

```bash
python3 scripts/batch_produce_celebrity_videos.py --count 10 --language en --card-layout flag_hero --duration-profile standard --max-attempts 30
```
