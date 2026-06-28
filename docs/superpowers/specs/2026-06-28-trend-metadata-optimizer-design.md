# Trend Metadata Optimizer Design

## Purpose

Celebrity videos already render well, but metadata is too repetitive and search-bland. The system needs metadata variants that are more searchable, more curiosity-driven, and less dependent on `Top 10 ...` templates.

## Scope

Add a metadata optimizer for review-time metadata selection. This feature does not change video scenes, facts, images, upload, analytics, or n8n orchestration.

## Behavior

For every rendered Celebrity review, generate a `metadata_variants` payload:

- 5 title variants
- 3 description variants
- 12-20 tags
- 3 thumbnail text suggestions
- 5-10 search keywords
- one trend angle
- score breakdown per title
- selected best title/description/tags/thumbnail text

Title variants should include mixed formats, not only `Top 10`:

- curiosity title
- direct search title
- comparison title
- trend/year title
- data shock title

All metadata must stay fact-safe. It may create curiosity but must not claim a trend, scandal, or result not supported by the content contract.

## Storage

Review artifacts store:

```json
{
  "metadata_variants": {},
  "selected_metadata": {
    "title": "...",
    "description": "...",
    "tags": [],
    "thumbnail_text": "..."
  }
}
```

Existing `youtube` fields stay for backward compatibility.

## UI

Review UI displays:

- selected metadata
- title variants with score
- description variants
- tags
- thumbnail text suggestions

MVP selection can be read-only. Editing/saving selected metadata is a later step.

## Failure Policy

If AI metadata generation fails, use deterministic fallback variants derived from the content contract. The fallback must still include non-`Top 10` title patterns.
