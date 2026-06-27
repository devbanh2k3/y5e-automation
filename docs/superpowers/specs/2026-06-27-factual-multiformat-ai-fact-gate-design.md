# Factual Multi-Format Content Strategy And AI Fact Gate Design

## Goal

Expand Celebrity production beyond repeated rankings while keeping every published claim factual, measurable, and suitable for the existing timeline video template. Add an independent AI fact-verification gate before image acquisition and rendering.

## Product Rules

- Content remains 100% factual; hypothetical or invented entertainment metrics are not allowed.
- The existing timeline slide structure and card layouts remain unchanged.
- AI is the verifier chosen for this version. External source URLs are not required.
- Verification status must be described internally as `ai_verified`, not source-verified.
- Public facts only. Reject private allegations, rumors, medical claims, undisclosed children, and unbounded lifetime estimates.

## Supported Content Formats

The strategy may select:

- `ranking`: ordered comparison from lower rank to number one.
- `count_comparison`: comparable public counts such as children, albums, films, awards, or number-one singles.
- `timeline`: dates, ages, career starts, or years active.
- `record_comparison`: public achievements and records with measurable values.
- `before_after`: the same metric at two explicit dates.
- `fact_collection`: independent measurable facts connected by one editorial theme.
- `binary_comparison`: public yes/no achievements such as winning an Oscar.

Open taxonomy remains enabled. New formats require explicit validation before selection rather than being accepted solely because AI proposed them.

## Topic Candidate Contract

Extend each Celebrity topic candidate with:

- `content_format`
- `metric_label`
- `metric_scope`
- `time_scope`
- `factual_basis`
- `measurability_score`
- `privacy_risk`

`metric_scope` must make the claim finite and testable. For example, "outfits worn during a named tour show" is valid; "all outfits ever worn" is rejected. A claim about children is accepted only when the people and counts are publicly acknowledged.

## Portfolio Selection

Candidate scoring keeps the current viral, data, novelty, image, and safety dimensions and adds format diversity and measurability. Deterministic validation runs before scoring.

Within one batch:

- Do not repeat `content_format` when enough valid alternatives exist.
- Do not repeat angle, metric, or metric scope.
- Preserve semantic topic deduplication and the existing angle cooldown.

Across batches:

- Track format in durable topic history.
- Apply a 10-video cooldown to an exact format-angle pair.
- Allow a format to return sooner with a materially different angle and metric.

The selector may relax format uniqueness only after one expanded candidate pass. It must never relax factual safety, measurability, semantic duplication, or privacy constraints.

## Content Contract Changes

Extend `content_contract_v2` without changing the schema version or existing required fields:

- Top level: `contentFormat`, `metricScope`, and `timeScope`.
- Scene level: `factClaim`, `factValue`, `factUnit`, `factAsOf`, and `factContext`.

Ranking scenes retain rank ordering. Other formats use their natural ordering, which must remain stable after verification.

The Content Agent receives the selected topic and must produce only its requested format. If the generated scenes violate the format contract, production fails before image acquisition.

## AI Fact Verification Contract

Add `fact_verification_contract_v1`:

```json
{
  "schema_version": "fact_verification_contract_v1",
  "verification_policy": "ai_only_independent_pass",
  "status": "ai_verified",
  "required_count": 10,
  "verified_count": 10,
  "corrected_count": 0,
  "rejected_count": 0,
  "items": [
    {
      "scene_index": 0,
      "person_name": "Example Person",
      "metric_label": "GRAMMY WINS",
      "original_value": "12",
      "verified_value": "12",
      "unit": "awards",
      "as_of": "2026",
      "status": "verified",
      "confidence": 0.92,
      "reason": "Consistent with established public knowledge",
      "knowledge_cutoff_risk": "low"
    }
  ]
}
```

Per-item statuses are `verified`, `corrected`, or `rejected`. The top-level status is `ai_verified` only when every item is verified or safely corrected and every confidence is at least `0.80`.

## Independent Verification Flow

1. Topic Strategy selects and reserves a factual multi-format topic.
2. Content Agent generates the initial content contract.
3. `AIFactVerificationAgent` receives the complete contract in a separate AI call with an adversarial verification prompt.
4. The verifier checks identity, metric definition, scope, value, unit, date, internal consistency, ordering, privacy, and plausibility.
5. Safe corrections are applied deterministically to a copied content contract.
6. The corrected contract is validated again.
7. Only then may Real Image Agent and renderer run.

The verifier must not see or reuse Content Agent reasoning. It receives only the structured claims. The current 9router AI client remains the provider boundary.

## Correction Rules

- Apply a correction only when confidence is at least `0.80` and the corrected value is explicit.
- Preserve the original value in the verification contract.
- Recompute ranking order after corrected numeric values.
- Reject ambiguous units, missing dates for time-sensitive metrics, conflicting person identity, private claims, and unmeasurable scope.
- Reject the whole topic when any scene is rejected or below threshold. Batch production then records the failure and requests a replacement topic through the existing mechanism.

## Template Semantics

Do not change timeline motion, slide structure, card dimensions, flag placement, image behavior, or selected card layout.

Card headers become format-aware:

- `ranking`: `TOP 10`, `TOP 9`, and so on.
- `fact_collection`: `FACT 1`, `FACT 2`, and so on.
- `timeline`: `MILESTONE`.
- `record_comparison`: `RECORD`.
- `before_after`: `THEN / NOW`.
- `count_comparison`: `COUNT`.
- `binary_comparison`: `YES / NO` based on the verified value.

Visible card text stays concise: person, metric label, verified value, and optional short context. No verification instructions or implementation labels appear in the video.

## Quality Gate And Review

Production Quality Gate must require and validate `fact_verification_contract_v1` before creating a pending review:

- Contract shape is valid.
- Item count matches scenes/cards.
- Every scene index matches.
- Every item is verified or corrected.
- Confidence is at least `0.80`.
- Corrected content values match rendered card values.
- Format-specific ordering and headers are valid.

Write `fact_verification_contract.json` beside existing review artifacts. Store it in the review record so reviewers can inspect original value, corrected value, confidence, reason, and cutoff risk.

## Failure Handling

- Invalid verifier JSON uses existing AI client retry behavior.
- A second invalid response fails the topic; it does not bypass the gate.
- Rejected or low-confidence scenes fail before downloading images or rendering.
- Batch replacement is limited by the existing replacement policy.
- AI/provider failure is reported separately from factual rejection.

## Testing

Focused tests must prove:

- Every supported format validates and produces the correct semantic header.
- Unbounded or private metrics are rejected before scoring.
- Batch selection prefers different formats, angles, metrics, and scopes.
- AI verification can verify, correct, and reject scenes.
- Corrections update content and ranking order before render.
- Confidence below `0.80` blocks the topic.
- Image acquisition and render are not called after fact rejection.
- Quality Gate rejects missing, mismatched, or low-confidence fact contracts.
- Review artifacts include the fact verification contract.
- Existing ranking videos and all current tests remain compatible.

## Non-Goals

- External web retrieval or source URL verification
- Channel analytics feedback
- Upload and scheduling
- New slide/template structure
- Hypothetical, parody, or fictional metrics
