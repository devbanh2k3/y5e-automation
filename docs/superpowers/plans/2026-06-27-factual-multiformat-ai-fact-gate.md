# Factual Multi-Format AI Fact Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce diverse factual Celebrity formats and block image acquisition/rendering unless an independent AI pass verifies or safely corrects every scene.

**Architecture:** Extend the existing topic/content contracts backward-compatibly, add a focused fact-verification contract plus agent, then insert verification between ContentAgent and RealImageAgent. Python computes format-aware card semantics; the existing timeline/card layout remains intact, while Quality Gate and review artifacts carry verification evidence.

**Tech Stack:** Python 3.14, asyncio, existing 9router OpenAI-compatible client, JSON-backed contracts/reviews, pytest/pytest-asyncio, TypeScript/React/Remotion, Vitest.

---

## File Structure

- Create `core/fact_verification.py`: fact contract construction, validation, correction application, and format ordering.
- Create `agents/ai_fact_verification_agent.py`: independent AI verification prompt and strict response normalization.
- Create `tests/test_fact_verification.py`: contract, correction, confidence, rejection, and ordering coverage.
- Create `tests/test_ai_fact_verification_agent.py`: AI response normalization and failure behavior.
- Modify `agents/topic_strategy_agent.py`: multi-format candidate fields, validation, scoring, diversity, and history.
- Modify `agents/content_agent.py`: enforce the selected format and emit structured fact claims.
- Modify `core/video_contract.py`: backward-compatible multi-format fields and semantic card headers.
- Modify `agents/pipeline.py`: run fact verification before RealImageAgent and render.
- Modify `core/quality_gate.py`: require fact verification for Celebrity production.
- Modify `core/reviews.py`: persist fact verification evidence.
- Modify `scripts/produce_celebrity_video.py`: write `fact_verification_contract.json`.
- Modify `video_engine/src/components/Card.tsx`: remove the fixed `RANK` label assumption for non-ranking headers.
- Modify focused Python and TypeScript tests beside each changed boundary.

### Task 1: Multi-Format Content Contract And Card Semantics

**Files:**
- Modify: `core/video_contract.py`
- Create: `tests/test_multiformat_video_contract.py`

- [x] **Step 1: Write failing format validation and header tests**

```python
import pytest

from core.video_contract import (
    VideoContractError,
    build_content_contract_v2,
    build_video_data_from_content_contract,
)


def scene(title="#1 Taylor Swift", value="14", **overrides):
    item = {
        "title": title,
        "voiceover": "A concise factual statement.",
        "caption": value,
        "image_prompt": "real editorial photo of Taylor Swift",
        "statusText": value,
        "countryCode": "US",
        "countryLabel": "UNITED STATES",
        "metricLabel": "GRAMMY WINS",
        "metricValue": value,
        "factClaim": "Taylor Swift has 14 Grammy wins",
        "factValue": value,
        "factUnit": "awards",
        "factAsOf": "2026",
        "factContext": "Grammy wins through 2026",
    }
    item.update(overrides)
    return item


def contract(content_format, scenes):
    return build_content_contract_v2(
        niche="celebrity", title="Facts", hook="Hook", target_audience="Fans",
        language="en", scenes=scenes, thumbnail_prompt="Thumbnail",
        youtube_title="Facts", youtube_description="Description",
        youtube_tags=["celebrity"], duration_target=60, cardLayout="flag_hero",
        contentFormat=content_format, metricScope="public records", timeScope="2026",
    )


@pytest.mark.parametrize(
    ("content_format", "value", "expected_header"),
    [
        ("ranking", "14", "TOP 1"),
        ("fact_collection", "14", "FACT 1"),
        ("timeline", "2006", "MILESTONE"),
        ("record_comparison", "14", "RECORD"),
        ("before_after", "2006 / 2026", "THEN / NOW"),
        ("count_comparison", "14", "COUNT"),
        ("binary_comparison", "YES", "YES"),
    ],
)
def test_build_video_data_uses_format_header(content_format, value, expected_header):
    payload = contract(content_format, [scene(value=value, factValue=value)])
    assert build_video_data_from_content_contract(payload)["cards"][0]["header"] == expected_header


def test_factual_format_rejects_unscoped_scene():
    payload = contract("count_comparison", [scene(factAsOf="", factContext="")])
    with pytest.raises(VideoContractError, match="factAsOf"):
        build_video_data_from_content_contract(payload)
```

- [x] **Step 2: Run the tests and verify RED**

Run: `python3 -m pytest tests/test_multiformat_video_contract.py -q`

Expected: FAIL because `build_content_contract_v2()` does not accept multi-format fields and headers remain ranking-only.

- [x] **Step 3: Implement backward-compatible multi-format fields**

Add optional `contentFormat: str | None = None`, `metricScope: str = ""`, and `timeScope: str = ""` parameters to `build_content_contract_v2()`. Only include the three new top-level keys when `contentFormat` is not `None`; this preserves the ability to distinguish legacy contracts. `build_video_data_from_content_contract()` treats a missing format as `ranking`. Define:

```python
CONTENT_FORMATS = {
    "ranking", "count_comparison", "timeline", "record_comparison",
    "before_after", "fact_collection", "binary_comparison",
}


def build_card_header(*, scene: dict[str, Any], content_format: str, index: int) -> str:
    if content_format == "ranking":
        return build_ranking_header(scene=scene, fallback_rank=index + 1)
    if content_format == "fact_collection":
        return f"FACT {index + 1}"
    if content_format == "timeline":
        return "MILESTONE"
    if content_format == "record_comparison":
        return "RECORD"
    if content_format == "before_after":
        return "THEN / NOW"
    if content_format == "count_comparison":
        return "COUNT"
    value = str(scene.get("factValue", scene.get("metricValue", ""))).strip().upper()
    return "YES" if value in {"YES", "TRUE", "1"} else "NO"
```

For contracts that explicitly include `contentFormat`, validate top-level scope and scene `factClaim`, `factValue`, `factUnit`, `factAsOf`, and `factContext`. Preserve legacy contracts that omit `contentFormat` by treating them as ranking contracts without requiring new fact fields.

- [x] **Step 4: Run focused and legacy contract tests**

Run: `python3 -m pytest tests/test_multiformat_video_contract.py tests/test_content_agent.py tests/test_pipeline_local_render.py -q`

Expected: PASS.

- [x] **Step 5: Commit contract semantics**

```bash
git add core/video_contract.py tests/test_multiformat_video_contract.py
git commit -m "feat: add factual multi-format content contracts"
```

### Task 2: Multi-Format Topic Strategy And Measurability

**Files:**
- Modify: `agents/topic_strategy_agent.py`
- Modify: `tests/test_topic_strategy_agent.py`

- [x] **Step 1: Write failing candidate and slate tests**

```python
def test_candidate_rejects_unbounded_or_private_metric():
    unbounded = normalize_candidate(candidate(
        content_format="count_comparison",
        metric_scope="all outfits ever worn",
        factual_basis="AI estimate",
        measurability_score=20,
        privacy_risk="low",
    ))
    private = normalize_candidate(candidate(
        content_format="count_comparison",
        metric_scope="unacknowledged children",
        factual_basis="rumor",
        measurability_score=90,
        privacy_risk="high",
    ))
    assert "measurable" in " ".join(validate_candidate(unbounded)).lower()
    assert "privacy" in " ".join(validate_candidate(private)).lower()


@pytest.mark.asyncio
async def test_strategy_prefers_distinct_formats_angles_metrics_and_scopes(agent, monkeypatch):
    monkeypatch.setattr(agent, "ai_json", fake_multiformat_candidate_payload)
    selected = await agent.run(count=3, language="en", batch_id="formats-1")
    assert len({item["content_format"] for item in selected}) == 3
    assert len({item["angle"] for item in selected}) == 3
    assert len({item["metric_label"] for item in selected}) == 3
    assert len({item["metric_scope"] for item in selected}) == 3
```

The fake payload must include valid ranking, timeline, and fact-collection candidates plus a higher-scored invalid unbounded candidate.

- [x] **Step 2: Run strategy tests and verify RED**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py -q`

Expected: FAIL because format, scope, measurability, and privacy are not normalized or selected.

- [x] **Step 3: Extend candidate normalization and deterministic validation**

Add required fields `content_format`, `metric_scope`, `factual_basis`, `measurability_score`, and `privacy_risk`; keep `time_scope`. Normalize measurability on the existing 0-10/0-100 score rules. Reject unknown formats, measurability below 80, `privacy_risk != "low"`, and explicitly unbounded scopes such as `all outfits ever worn` or `number of times ever performed` when no named dataset/event/date bounds the claim. Allow all-time metrics backed by finite public datasets such as Grammy wins or box-office records.

Update the AI prompt to request all fields and generate at least four different formats. Add measurability to the score total by folding it into `data_score`:

```python
effective_data_score = min(item["data_score"], item["measurability_score"])
```

Selection requires unique format, angle, metric, and scope on the first pass. The expanded pass may reuse format but never angle, metric, scope, safety, or measurability failures.

- [x] **Step 4: Run strategy tests**

Run: `python3 -m pytest tests/test_topic_strategy_agent.py tests/test_topic_history.py -q`

Expected: PASS.

- [x] **Step 5: Commit strategy changes**

```bash
git add agents/topic_strategy_agent.py tests/test_topic_strategy_agent.py
git commit -m "feat: diversify factual celebrity content formats"
```

### Task 3: Fact Verification Contract And Safe Corrections

**Files:**
- Create: `core/fact_verification.py`
- Create: `tests/test_fact_verification.py`

- [x] **Step 1: Write failing contract, rejection, and correction tests**

```python
import pytest

from core.fact_verification import (
    FactVerificationError,
    apply_fact_corrections,
    build_fact_verification_contract_v1,
    validate_fact_verification_contract_v1,
)


def item(index, status="verified", confidence=0.9, original="10", verified="10"):
    return {
        "scene_index": index,
        "person_name": f"Person {index}",
        "metric_label": "AWARDS",
        "original_value": original,
        "verified_value": verified,
        "unit": "awards",
        "as_of": "2026",
        "status": status,
        "confidence": confidence,
        "reason": "Independent AI consistency check",
        "knowledge_cutoff_risk": "low",
    }


def test_contract_counts_verified_corrected_and_rejected_items():
    contract = build_fact_verification_contract_v1(
        [item(0), item(1, status="corrected", original="9", verified="11")]
    )
    validate_fact_verification_contract_v1(contract)
    assert contract["status"] == "ai_verified"
    assert contract["verified_count"] == 1
    assert contract["corrected_count"] == 1


@pytest.mark.parametrize("status,confidence", [("rejected", 0.95), ("verified", 0.79)])
def test_contract_blocks_rejected_or_low_confidence_item(status, confidence):
    contract = build_fact_verification_contract_v1([item(0, status=status, confidence=confidence)])
    with pytest.raises(FactVerificationError):
        validate_fact_verification_contract_v1(contract, require_ai_verified=True)


def test_corrections_update_values_and_rerank_numeric_ranking(content_contract):
    verification = build_fact_verification_contract_v1([
        item(0, status="corrected", original="10", verified="30"),
        item(1, status="verified", original="20", verified="20"),
    ])
    corrected = apply_fact_corrections(content_contract, verification)
    assert corrected["scenes"][0]["factValue"] == "20"
    assert corrected["scenes"][1]["factValue"] == "30"
    assert corrected["scenes"][1]["title"].startswith("#1 ")
```

- [x] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_fact_verification.py -q`

Expected: FAIL with missing `core.fact_verification`.

- [x] **Step 3: Implement strict contract and correction APIs**

Define `MIN_FACT_CONFIDENCE = 0.80`, `FactVerificationError`, contract builder/validator, and `apply_fact_corrections()`. Deep-copy content before editing. A corrected item updates `factValue`, `metricValue`, `caption`, and `statusText`; preserve original values only in the verification contract. Parse numeric values with units removed for ranking order, reject reranking when values cannot be compared, sort ranking ascending so number one remains last, and rewrite `#N` prefixes consistently.

- [x] **Step 4: Run contract tests**

Run: `python3 -m pytest tests/test_fact_verification.py -q`

Expected: PASS.

- [x] **Step 5: Commit fact contract**

```bash
git add core/fact_verification.py tests/test_fact_verification.py
git commit -m "feat: add ai fact verification contract"
```

### Task 4: Independent AI Fact Verification Agent

**Files:**
- Create: `agents/ai_fact_verification_agent.py`
- Create: `tests/test_ai_fact_verification_agent.py`

- [x] **Step 1: Write failing agent tests**

```python
import pytest

from agents.ai_fact_verification_agent import AIFactVerificationAgent
from core.fact_verification import FactVerificationError


@pytest.mark.asyncio
async def test_agent_sends_structured_claims_and_returns_contract(monkeypatch, content_contract):
    agent = AIFactVerificationAgent()
    captured = {}
    async def fake_ai_json(prompt, system=None, **kwargs):
        captured["prompt"] = prompt
        return {"items": [verified_response_item(0), verified_response_item(1)]}
    monkeypatch.setattr(agent, "ai_json", fake_ai_json)
    result = await agent.run(content_contract=content_contract)
    assert result["status"] == "ai_verified"
    assert "factClaim" in captured["prompt"]
    assert "image_prompt" not in captured["prompt"]


@pytest.mark.asyncio
async def test_agent_rejects_missing_scene_or_low_confidence(monkeypatch, content_contract):
    agent = AIFactVerificationAgent()
    async def fake_ai_json(prompt, system=None, **kwargs):
        return {"items": [verified_response_item(0, confidence=0.6)]}
    monkeypatch.setattr(agent, "ai_json", fake_ai_json)
    with pytest.raises(FactVerificationError):
        await agent.run(content_contract=content_contract)
```

- [x] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_ai_fact_verification_agent.py -q`

Expected: FAIL with missing agent module.

- [x] **Step 3: Implement adversarial verification prompt and normalization**

Implement `AIFactVerificationAgent(BaseAgent).run(*, content_contract: dict[str, Any])`. Send only scene index, person name, fact claim/value/unit/as-of/context, format, scope, and ordering. The system prompt must instruct the model to challenge the claims independently, return one item per scene, never invent missing private facts, and mark uncertainty as rejected. Normalize scene indices and status values, then call `build_fact_verification_contract_v1()` and strict validation.

- [x] **Step 4: Run agent and contract tests**

Run: `python3 -m pytest tests/test_ai_fact_verification_agent.py tests/test_fact_verification.py -q`

Expected: PASS.

- [x] **Step 5: Commit verification agent**

```bash
git add agents/ai_fact_verification_agent.py tests/test_ai_fact_verification_agent.py
git commit -m "feat: verify celebrity facts with independent ai pass"
```

### Task 5: Content Agent And Pipeline Fact Gate

**Files:**
- Modify: `agents/content_agent.py`
- Modify: `agents/pipeline.py`
- Modify: `tests/test_content_agent.py`
- Modify: `tests/test_pipeline_local_render.py`

- [x] **Step 1: Write failing content-format and pipeline-order tests**

Add a ContentAgent test that passes a selected `timeline` topic and asserts top-level multi-format fields plus every scene fact field are preserved.

Add a Pipeline test with fakes recording calls:

```python
events = []

class FakeFactAgent:
    async def run(self, *, content_contract):
        events.append("fact")
        return verified_fact_contract(content_contract)

class FakeImageAgent:
    async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
        events.append("image")
        assert content_contract["scenes"][0]["factValue"] == "corrected value"
        return verified_image_contract(topic_id, content_contract)

assert events == ["fact", "image", "render"]
```

Add a rejection test where FakeFactAgent raises `FactVerificationError`; assert image and render fakes are never called.

- [x] **Step 2: Run focused tests and verify RED**

Run: `python3 -m pytest tests/test_content_agent.py tests/test_pipeline_local_render.py -q`

Expected: FAIL because ContentAgent omits fact fields and Pipeline has no fact step.

- [x] **Step 3: Generate structured facts and insert gate before images**

Update the ContentAgent prompt/normalizer to require selected topic format/scope/time and scene fact fields. Legacy seeded fallback remains ranking-compatible.

In `Pipeline.run_local_render()`:

```python
fact_verification_contract = await AIFactVerificationAgent().run(
    content_contract=content_contract
)
content_contract = apply_fact_corrections(
    content_contract, fact_verification_contract
)
video_data = build_video_data_from_content_contract(content_contract)
image_verification_contract = await RealImageAgent().run_for_content_contract(
    topic_id=topic_id,
    content_contract=content_contract,
    strict=True,
)
```

Return the fact contract in the pipeline result. Do not catch `FactVerificationError`; batch replacement already handles production failures.

- [x] **Step 4: Run focused pipeline tests**

Run: `python3 -m pytest tests/test_content_agent.py tests/test_pipeline_local_render.py tests/test_batch_produce_celebrity_videos.py -q`

Expected: PASS.

- [x] **Step 5: Commit pipeline integration**

```bash
git add agents/content_agent.py agents/pipeline.py tests/test_content_agent.py tests/test_pipeline_local_render.py
git commit -m "feat: gate celebrity rendering on ai fact verification"
```

### Task 6: Production Quality Gate, Review, And Artifacts

**Files:**
- Modify: `core/quality_gate.py`
- Modify: `core/reviews.py`
- Modify: `scripts/produce_celebrity_video.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_reviews.py`
- Modify: `tests/test_produce_celebrity_video.py`

- [x] **Step 1: Write failing evidence persistence and gate tests**

Add tests asserting Celebrity Quality Gate rejects missing fact contracts, low confidence, item/scene mismatch, and rendered card values that differ from corrected values. Add passing coverage for a complete contract.

Add review/artifact tests:

```python
review = await create_review(
    job_id="", topic_id=1, video_id=2, file_path="/tmp/final.mp4",
    content_contract={"title": "Facts"},
    image_verification_contract={"status": "verified"},
    quality_gate={"status": "passed"},
    fact_verification_contract={"schema_version": "fact_verification_contract_v1"},
    youtube_title="Facts", youtube_description="Description",
    youtube_tags=["celebrity"], thumbnail_prompt="Thumbnail",
)
assert (await get_review(review["review_id"]))["fact_verification_contract"]["schema_version"] \
    == "fact_verification_contract_v1"

artifacts = write_artifacts(result=result, review=review)
assert json.loads(Path(artifacts["fact_verification_contract_path"]).read_text()) \
    == review["fact_verification_contract"]
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `python3 -m pytest tests/test_quality_gate.py tests/test_reviews.py tests/test_produce_celebrity_video.py -q`

Expected: FAIL because fact verification is neither required nor persisted.

- [x] **Step 3: Extend gate and persistence boundaries**

Add `fact_verification_contract` to `run_production_quality_gate()` and `create_review()`. Validate with `validate_fact_verification_contract_v1(require_ai_verified=True)`, match item count/index/value against corrected scenes/cards, and add per-scene confidence checks. Pass the contract from Pipeline to Quality Gate and Review. Write `fact_verification_contract.json` next to existing artifacts and expose its path in producer output.

- [x] **Step 4: Run evidence and pipeline tests**

Run: `python3 -m pytest tests/test_quality_gate.py tests/test_reviews.py tests/test_produce_celebrity_video.py tests/test_pipeline_local_render.py -q`

Expected: PASS.

- [ ] **Step 5: Commit production evidence**

```bash
git add core/quality_gate.py core/reviews.py scripts/produce_celebrity_video.py tests/test_quality_gate.py tests/test_reviews.py tests/test_produce_celebrity_video.py
git commit -m "feat: persist and enforce ai fact evidence"
```

### Task 7: Remove Ranking-Only Labels From Card Layouts

**Files:**
- Create: `video_engine/src/components/card-semantics.ts`
- Create: `video_engine/src/components/card-semantics.test.ts`
- Modify: `video_engine/src/components/Card.tsx`
- Modify: `video_engine/package.json`
- Modify: `video_engine/package-lock.json`

- [ ] **Step 1: Install the existing-toolchain-compatible test runner**

Run: `cd video_engine && npm install --save-dev vitest`

Expected: `package.json` and `package-lock.json` add Vitest without changing production dependencies.

- [ ] **Step 2: Write a failing semantic helper test**

```typescript
import {describe, expect, it} from "vitest";
import {getHeaderStat} from "./card-semantics";

describe("getHeaderStat", () => {
  it("preserves ranking semantics", () => {
    expect(getHeaderStat("TOP 3")).toEqual({label: "RANK", value: "#3"});
  });

  it("uses type semantics for factual formats", () => {
    expect(getHeaderStat("FACT 1")).toEqual({label: "TYPE", value: "FACT 1"});
    expect(getHeaderStat("MILESTONE")).toEqual({label: "TYPE", value: "MILESTONE"});
  });
});
```

- [ ] **Step 3: Run the helper test and verify RED**

Run: `cd video_engine && npx vitest run src/components/card-semantics.test.ts`

Expected: FAIL because `card-semantics.ts` does not exist.

- [ ] **Step 4: Implement and consume semantic stat labels**

Create:

```tsx
export const getHeaderStat = (header: string): {label: string; value: string} => {
  const isRankingHeader = /^TOP\s+\d+$/i.test(header);
  return {
    label: isRankingHeader ? "RANK" : "TYPE",
    value: isRankingHeader ? header.replace(/^TOP\s*/i, "#") : header,
  };
};
```

Import `getHeaderStat()` in `Card.tsx` and pass its label/value to the existing `StatBlock`. Do not alter dimensions, motion, colors, image fit, or layout selection.

- [ ] **Step 5: Run helper tests and TypeScript build**

Run: `cd video_engine && npx vitest run src/components/card-semantics.test.ts && npm run build`

Expected: PASS.

- [ ] **Step 6: Commit renderer semantics**

```bash
git add video_engine/src/components/card-semantics.ts video_engine/src/components/card-semantics.test.ts video_engine/src/components/Card.tsx video_engine/package.json video_engine/package-lock.json
git commit -m "fix: render non-ranking card semantics"
```

### Task 8: Full Verification And Real AI Probe

**Files:**
- Modify only files above if verification exposes a defect.

- [ ] **Step 1: Run all Python tests and static diff checks**

```bash
git diff --check
python3 -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run video-engine verification**

```bash
cd video_engine
npx vitest run
npm run build
```

Expected: tests and build PASS.

- [ ] **Step 3: Run a no-render 9router probe**

Generate three topics through `TopicStrategyAgent` and assert distinct formats, angles, metrics, and scopes. Build one content contract and pass it through `AIFactVerificationAgent`, but do not call RealImageAgent or renderer. Print only topic metadata and fact status/confidence, then mark probe reservations failed with `fact_gate_probe_only`.

Expected: diverse topics and a structurally valid verification result, or a clear factual rejection without rendering side effects.

- [ ] **Step 4: Verify branch state and commit any probe-driven fix**

Run: `git status --short --branch`

Expected: branch contains only deliberately ignored runtime output and no uncommitted source changes.

The first full acceptance command after merge remains:

```bash
python3 scripts/batch_produce_celebrity_videos.py --count 3 --language en --card-layout flag_hero
```

The expected batch contains diverse formats, only AI-verified/corrected facts, pending reviews with fact evidence, and replacements for rejected topics.
