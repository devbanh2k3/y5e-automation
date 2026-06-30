# Native-Only Render and Review Delivery Design

## Objective

Make production rendering use the host hardware path exclusively, keep background music playing for the full video, and make review assets easier to download and reuse.

The change has four outcomes:

1. Production never silently falls back to Docker rendering.
2. A short background track loops until the video ends.
3. A downloaded review MP4 uses the video title as its filename.
4. Review metadata exposes tags as a comma-separated copy-friendly value.

## Native-Only Rendering

When native rendering is enabled, the pipeline requires a live native render runner. Docker remains the control plane for API, queue, workers, and storage, but it must not execute Remotion rendering.

The runtime behavior is:

- A live native runner accepts and renders the job using the configured host encoder.
- A missing runner fails before rendering with a clear operational error.
- A failed native render returns its original failure and never invokes the Docker renderer.
- Native rendering disabled is still supported for explicit development and test configurations. Production configuration enables native rendering and uses an error-only fallback policy.

Startup and readiness messages should make the missing-native-runner condition identifiable. Existing render result metadata continues to identify the renderer and encoder.

## Background Music Loop

Every Remotion composition that accepts `musicPath` plays the selected track with looping enabled. The audio repeats seamlessly for the complete composition duration instead of ending when the source file ends.

This applies consistently to ranking, timeline, and comparison compositions. It does not concatenate or rewrite the source audio file, so rendering does not require an additional preprocessing command.

## Review Video Filename

The review video endpoint continues to serve MP4 inline so browsers and Telegram can preview it. Its `Content-Disposition` filename is derived from the selected YouTube title, falling back to the original filename when no title is available.

Filename normalization must:

- remove filesystem-reserved characters and control characters;
- collapse repeated whitespace;
- avoid Windows reserved names;
- enforce a practical maximum length while preserving `.mp4`;
- produce a non-empty fallback filename.

Example:

```text
Top 50 Richest Singers in 2026.mp4
```

## Copy-Friendly Tags

Review data exposes the selected YouTube tags as one comma-separated string:

```text
celebrity, richest singers, net worth, famous people, 2026
```

Tags do not include `#`; hashtags in the video description remain separate. The Review UI displays the value in a dedicated tags field with a `Copy tags` action. Telegram review details render the same comma-separated value in a copy-friendly monospace block where that detail view is available.

The selected metadata remains the source of truth. If it has no tags, the endpoint falls back to the review's YouTube tags.

## Error Handling

- Native runner unavailable: fail the production task with a specific native-runner error.
- Native render failure: preserve the native error; do not hide it behind a generic Docker fallback failure.
- Missing or invalid title: use `video.mp4` or the valid original basename.
- Empty tags: show an empty state instead of a copy button that copies meaningless content.
- Clipboard unavailable: retain selectable tag text and show a concise UI error.

## Testing

Automated tests must verify:

1. Native rendering does not call Docker when the runner is unavailable or the native job fails.
2. All music-enabled Remotion compositions enable looping.
3. Review video responses use a safe title-based MP4 filename and preserve inline playback.
4. Filename normalization handles reserved characters, long titles, empty titles, and Windows reserved names.
5. Review UI exposes comma-separated tags and copies the exact displayed value.
6. Existing review ownership and authorization boundaries remain unchanged.

## Acceptance Criteria

The implementation is accepted when:

- production configuration has native rendering enabled and Docker fallback disabled;
- a forced native failure cannot trigger a Docker render;
- a music track shorter than the target video repeats through the final frame;
- downloading a review produces a safe filename based on its selected title;
- tags are displayed separately with comma separators and can be copied in one action;
- focused backend, frontend, and render tests pass.
