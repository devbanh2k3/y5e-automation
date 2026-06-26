# Real Image Source Reliability v2 Design

## Goal

Make the strict real-image pipeline actually render celebrity videos with verified real photos when Wikimedia original-file downloads are blocked. The system must keep the existing video template unchanged and must not fall back to AI images, random stock images, or placeholders.

## Current Problem

`RealImageAgent` can query Wikimedia Commons metadata after using a Wikimedia-compliant User-Agent. However, live smoke testing showed that direct downloads from `upload.wikimedia.org` original file URLs can return `403 Forbidden` in this runtime environment. The strict gate correctly refuses to render with placeholders, but the source/download layer needs a more reliable Wikimedia path.

## Non-Negotiable Requirements

- Keep strict identity verification.
- Add strict content-context verification so the accepted image matches the scene/person, not just a loose keyword.
- Keep source URL, image URL, license, attribution, local path, confidence, and reject reason metadata.
- Keep `content_contract_v2` and `TimelineVideo`; this feature only changes source lookup and image download reliability.
- Do not use AI-generated celebrity portraits.
- Do not use Picsum, random web thumbnails, social media scraping, search-engine thumbnails, or unlicensed images.
- If all verified real-image sources fail, return missing-image metadata and block production-looking render.

## Content Match Guard

The existing token match is not enough for names such as `Jay-Z`, because generic search results can match unrelated entities like `John Jay`. Add a deterministic content match layer before any candidate can be accepted.

Each candidate should produce these fields:

- `identity_check_status`: `passed`, `uncertain`, or `failed`.
- `identity_confidence`: float from `0.0` to `1.0`.
- `content_match_status`: `passed`, `uncertain`, or `failed`.
- `content_match_reason`: short explanation for review/debugging.
- `is_group_photo`: boolean derived from metadata when obvious.
- `needs_human_review`: boolean.

MVP rules:

- Exact normalized full-name phrase match in title/description/source metadata is required for `identity_check_status=passed`.
- Weak token-only matches are `uncertain`, not `passed`.
- For hyphen/stage names like `Jay-Z`, normalize punctuation but require the distinctive full stage name or a curated alias. `John Jay` must not pass for `Jay-Z`.
- Reject obvious unrelated media types by metadata/source URL: PDFs, books, paintings of unrelated historical figures, diagrams, logos, fan art, memes, and non-photo files.
- Reject candidates where metadata indicates a group photo unless the person name appears strongly and no solo image is available; MVP should mark group photos as `uncertain` and avoid rendering them in strict mode.
- For celebrity ranking videos, accepted images should be portraits, performance photos, red-carpet/event photos, or official/encyclopedic photos of the named person.

Production strict render rule:

- license check must pass,
- identity check must pass,
- content match must pass,
- image download and PIL validation must pass.

Any `uncertain` or `failed` identity/content result blocks strict render and becomes review metadata.

## Recommended Approach

Use a source adapter waterfall inside `RealImageAgent`:

1. **Commons Search Thumbnail Adapter**
   - Query Commons API with `iiprop=url|extmetadata` and `iiurlwidth=1200`.
   - Prefer `thumburl` for download.
   - Keep `url` as the original image URL metadata.
   - Use `descriptionurl` as source URL.

2. **Wikipedia Summary Adapter**
   - Query Wikipedia REST summary by exact person name.
   - Use `thumbnail.source` or `originalimage.source` as the downloadable image when present.
   - Use the summary page URL as source URL.
   - This adapter must still verify person-name tokens against `title`, `displaytitle`, description, and page URL text.
   - License may be unknown from summary alone, so this adapter is allowed only as `pending_review` unless paired with a license-bearing Commons source. For MVP implementation, use it as a candidate discovery path but do not mark it verified without license metadata.

3. **Wikidata P18 Adapter**
   - Query Wikidata for image claim `P18` from an exact person label.
   - Resolve the file through Commons API to get license and thumbnail metadata.
   - Use the same identity/license checks as Commons Search.

The first implementation should complete adapter 1 fully and add testable structure for adapters 2 and 3. Adapter 1 is the critical fix because Commons API can provide `thumburl`, which avoids relying only on original file URLs.

## Candidate Model

`RealImageAgent.extract_wikimedia_candidate()` should return:

- `download_url`: preferred URL to download, usually `thumburl`.
- `image_url`: canonical original image URL from Wikimedia metadata.
- `source_url`: Commons file page or verified source page.
- `license`: license label.
- `attribution`: attribution text.
- `metadata_text`: normalized metadata used for identity matching.
- `source_adapter`: adapter name, for example `commons_search_thumbnail`.
- `identity_check_status`, `identity_confidence`, `content_match_status`, `content_match_reason`, `is_group_photo`, and `needs_human_review`.

`image_url` remains part of the verification contract for provenance. `download_url` is an internal processing field and does not need to be stored in the final contract unless useful for debugging.

## Download Rules

- Prefer `download_url` when available.
- Fall back to `image_url` only if `download_url` is absent.
- Reject non-image content types before PIL processing.
- Reject files smaller than current minimum dimensions.
- Save processed local render assets as `output/topics/<topic_id>/images/real_<scene_index>.webp`.
- If a candidate download fails, try the next verified candidate; do not fail the whole person on the first blocked URL.

## Error And Review Behavior

When strict mode cannot verify every image:

- Do not render with placeholders.
- Return or raise a clear missing-image error naming the missing people.
- The missing item should preserve a reviewable `reject_reason`, for example `all verified Wikimedia thumbnail candidates failed to download`.

In a later review-gate improvement, failed image contracts should be persisted even when render is blocked. That is out of scope for this source reliability fix unless it is needed to keep existing tests coherent.

## Testing Strategy

Unit tests should cover:

- Commons candidate extraction prefers `thumburl` as `download_url`.
- Commons candidate still stores original `url` as `image_url`.
- Full-name identity matching accepts `Celine Dion` metadata for `Celine Dion`.
- Full-name identity matching rejects `John Jay` metadata for `Jay-Z`.
- Content match rejects PDFs, books, unrelated historical portraits, fan art, and obvious non-photo files by metadata/source URL.
- Group-photo metadata is marked `uncertain` or review-needed in strict mode.
- `_process_verified_candidate` downloads `download_url` when present.
- `_process_verified_candidate` rejects non-image content types before PIL.
- `_find_verified_image` tries the next candidate when one download fails.
- Existing strict contract tests still pass.
- Pipeline tests still prove template remains `timeline`.

Live smoke:

- Run celebrity local render after implementation.
- Accept either:
  - verified render succeeds with real local `.webp` images, or
  - strict gate fails with a clear source/download reason.
- Do not weaken strict mode to force a render.

## Out Of Scope

- Paid image APIs.
- Browser automation scraping.
- Face recognition.
- AI-generated images.
- Manual image upload UI.
- Per-item review endpoints.
- Changing the video template.

## Success Criteria

- Commons API candidates can use `thumburl` from `iiurlwidth=1200`.
- Download attempts are more reliable than original file URL only.
- Candidate provenance remains auditable.
- Strict render gate remains intact.
- Tests pass and live smoke behavior is explicit.
