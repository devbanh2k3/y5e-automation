# Real Image Agent MVP + Image Verification Contract Design

## Goal

Build a strict real-image pipeline for celebrity data-comparison videos. The system must use real sourced photos, verify that each image matches the intended person, and keep the existing video template unchanged.

## Non-Negotiable Requirements

- Do not generate AI images for celebrities.
- Do not use random stock, placeholder, Picsum, or prompt-only images for celebrity render output.
- Do not render a celebrity video as production-ready when any required person image is missing or unverified.
- Keep the current `TimelineVideo`/`content_contract_v2` render path. This feature changes image assets and metadata, not the video template.
- Every accepted image must have a source URL, image URL, license label, attribution text, local file path, and verification status.

## Source Policy

The MVP uses a conservative source policy:

- Primary source: Wikimedia Commons API.
- Acceptable page origins: `commons.wikimedia.org`, `wikimedia.org`, `wikipedia.org`.
- Acceptable license strings include public domain, CC0, CC BY, and CC BY-SA.
- Rejected sources include search-engine thumbnails, social media, stock-photo sites, random placeholder services, and generic web images without clear licensing.

This is intentionally narrower than the existing `ImageAgent` waterfall. The older agent can remain for non-celebrity or generic videos, but celebrity videos must use the strict real-image path.

## Image Verification Contract

Add a contract named `image_verification_contract_v1`. It is stored inside the render/review payload and can also be saved beside generated topic assets.

Top-level fields:

- `schema_version`: must be `image_verification_contract_v1`.
- `topic_id`: numeric topic id.
- `source_policy`: `wikimedia_commons_strict`.
- `required_count`: number of people that need images.
- `verified_count`: number of accepted images.
- `status`: `verified`, `pending_review`, or `rejected`.
- `items`: one item per person/scene.

Each item contains:

- `scene_index`: zero-based scene index.
- `person_name`: expected person name, for example `Celine Dion`.
- `expected_title`: scene title, for example `#10 Celine Dion`.
- `status`: `verified`, `missing_image`, or `rejected`.
- `confidence`: float from `0.0` to `1.0`.
- `local_path`: absolute or topic-relative path to downloaded image when accepted.
- `render_image_path`: path passed to Remotion, for example `images/real_0.webp`.
- `source_url`: Wikimedia file page or canonical source page.
- `image_url`: direct downloaded image URL.
- `license`: license label from Wikimedia metadata.
- `attribution`: attribution text from Wikimedia metadata.
- `reject_reason`: empty for verified items, otherwise a human-readable reason.

Contract status rules:

- `verified`: all items are verified.
- `pending_review`: at least one item is missing or rejected, but enough metadata exists for a human to inspect.
- `rejected`: the contract is malformed or a required invariant is violated.

## RealImageAgent

Create `agents/real_image_agent.py` with class `RealImageAgent`.

Public API:

```python
async def run_for_content_contract(
    self,
    *,
    topic_id: int,
    content_contract: dict[str, Any],
    strict: bool = True,
) -> dict[str, Any]:
    ...
```

Behavior:

1. Extract the person name from each celebrity ranking scene. MVP extraction reads the scene title format `#10 Celine Dion` and returns `Celine Dion`.
2. Query Wikimedia Commons for each person with a search like `Celine Dion portrait`.
3. Evaluate candidates in order:
   - candidate has image metadata,
   - direct image URL exists,
   - license is whitelisted,
   - Wikimedia title/caption/metadata contains the expected person name or strong name tokens,
   - image downloads successfully,
   - image can be opened by PIL,
   - image dimensions meet minimum size.
4. Save accepted images into `output/topics/<topic_id>/images/real_<scene_index>.webp`.
5. Return `image_verification_contract_v1`.
6. When `strict=True`, raise a clear error if any required image is not verified. The pipeline catches this and creates/returns pending-review metadata instead of silently rendering with wrong images.

The MVP does not need face recognition. It uses deterministic source and metadata verification first. Vision verification through 9router can be added later as a second-pass guard.

## Content-To-Render Integration

Add a helper that applies verified image paths to existing render data:

```python
def apply_verified_images_to_video_data(
    video_data: dict[str, Any],
    image_contract: dict[str, Any],
) -> dict[str, Any]:
    ...
```

Rules:

- Do not change `video_data["template"]`.
- Do not change titles, voiceover, status text, or durations.
- For each verified item, set `video_data["cards"][scene_index]["imagePath"]` to the item's `render_image_path`.
- Attach `video_data["image_verification_contract"]`.
- If any item is not verified, raise `VideoContractError`.

## Pipeline Integration

Update `Pipeline.run_local_render(category="Celebrity")`:

1. Build `content_contract_v2` as today.
2. Build `video_data` as today, still using the timeline template.
3. Run `RealImageAgent.run_for_content_contract(topic_id=1, content_contract=content_contract, strict=True)`.
4. Apply verified image paths to `video_data`.
5. Render only if the image contract is fully verified.
6. Include `image_verification_contract` in the review artifact and result summary.

If image verification fails:

- Do not render a production-looking MP4 with placeholders.
- Return `status` as `pending_review` or fail the local render with a clear message depending on existing worker behavior.
- Persist enough metadata for the user to see which person/image failed.

For the first implementation pass, a local render may still be allowed in tests through mocked verified image contracts. Real network calls should be isolated behind the agent methods and mocked in unit tests.

## Review Gate

Extend review artifacts to include `image_verification_contract`. The existing review endpoints can return this payload without new routes in the MVP.

The reviewer must be able to inspect:

- which image was used for each person,
- where it came from,
- what license it has,
- why an item was rejected or missing.

Per-item approve/reject can come later. MVP review remains whole-video approve/reject.

## 9router Usage

9router should not be used to generate celebrity images.

Allowed 9router usage in this feature:

- later: text-based source sanity checks,
- later: optional vision-based identity verification if a free/cheap vision model is available,
- later: explanation of rejection reasons for review UX.

The MVP must be useful without 9router by using deterministic Wikimedia metadata checks.

## Testing Strategy

Unit tests:

- Build and validate `image_verification_contract_v1`.
- Reject contracts with missing source URL, image URL, license, or local path for verified items.
- Confirm license whitelist accepts public domain, CC BY, and CC BY-SA.
- Confirm name-token matching accepts `Celine Dion` metadata for `Celine Dion` and rejects unrelated metadata.
- Confirm `apply_verified_images_to_video_data` changes only `imagePath` and preserves `template`.
- Confirm pipeline celebrity local render calls the real image agent and passes image verification data into review artifacts.

Network tests are not required for CI. Use mocked Wikimedia responses and mocked image downloads for deterministic tests.

## Out Of Scope For MVP

- Full web-wide image search.
- Social-media scraping.
- Paid image providers.
- AI-generated portraits.
- Face recognition.
- Per-item review endpoints.
- Template/layout redesign.
- YouTube upload changes.

## Success Criteria

- Celebrity local render cannot silently use placeholder images when strict real images are required.
- A verified contract can replace every card image path with a real downloaded image path.
- Review artifacts expose image source, license, attribution, confidence, and reject reasons.
- Existing timeline template remains unchanged.
- Tests prove the new image verification contract and pipeline integration behavior.
