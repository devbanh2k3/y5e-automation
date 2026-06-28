# Multi-Channel YouTube Publishing Design

## Purpose

Extend the existing Telegram production control plane so each authorized Telegram user can connect and manage multiple YouTube channels, select one channel for each production batch, and publish an approved video to that channel through a reliable background upload queue.

The feature must preserve strict tenant isolation: a user cannot list, select, disconnect, or publish to a channel owned by another user. Approval publishes immediately with YouTube `privacyStatus=public` after the upload completes.

## Scope

This increment includes:

- Google OAuth connection initiated from Telegram.
- Multiple YouTube channels per Telegram user.
- Channel selection before each production batch.
- Immutable channel assignment on the batch and its tasks.
- Approve-to-upload queue integration.
- A dedicated Docker upload worker.
- Resumable YouTube upload, token refresh, retries, and idempotency.
- Telegram notifications for upload progress and outcomes.
- Operational support for a temporary Cloudflare Quick Tunnel.

This increment excludes:

- YouTube analytics ingestion or channel-learning loops.
- Scheduled publishing.
- Automatic channel selection by an agent.
- Uploading through n8n.
- Cross-user channel sharing or administrator impersonation.
- Uploading to platforms other than YouTube.

## Decisions

- Uploads run in a dedicated Python worker, not synchronously in Telegram or the API.
- n8n may consume events later, but it does not own OAuth credentials or transfer MP4 files.
- Every batch requires an explicit channel selection.
- The selected channel is persisted when the batch is created and cannot change during review.
- Approving a review creates one upload job with public visibility.
- Quick Tunnel is supported for testing, but a stable named tunnel or domain is required for dependable operation.

## Architecture

### Channel Registry

The channel registry owns connected YouTube channel identities and their relationship to Telegram users. A channel record contains:

- Internal channel ID.
- Owning Telegram user ID.
- YouTube channel ID and display title returned by the YouTube API.
- Encrypted refresh token and token metadata.
- Granted OAuth scopes.
- Connection status: `active`, `auth_required`, or `disconnected`.
- Created, updated, and last successfully refreshed timestamps.

The combination of owner and YouTube channel ID is unique. Reconnecting the same channel updates its credential instead of creating duplicates.

### OAuth Service

The API exposes start and callback endpoints for the server-side Google OAuth flow.

1. Telegram requests a connection URL for an authenticated Telegram user.
2. The server creates a cryptographically random, single-use OAuth state tied to that user and an expiration time.
3. The browser opens Google consent with `access_type=offline`, the minimum YouTube scopes required for channel identity and upload, and an exact callback URI derived from configuration.
4. The callback consumes the state, exchanges the code, retrieves the authenticated YouTube channel identity, encrypts the refresh token, and upserts the channel under the initiating user.
5. The API shows a minimal success or error page and sends a Telegram result notification.

OAuth state must expire within ten minutes and be consumed atomically. The callback must never accept a Telegram user ID directly from query parameters as proof of ownership.

### Production Assignment

Telegram's create flow lists only active channels owned by the requesting user. The user selects a channel before entering or confirming batch settings.

The internal channel ID is written to the production batch. Production tasks inherit that assignment. Render and review artifacts expose the destination channel title for clarity, but channel ownership and assignment are always resolved from the database.

A batch cannot be created without an active owned channel. A later disconnect prevents upload but does not silently redirect the batch to another channel.

### Review and Upload Queue

Approval remains a fast state transition. It does not upload the MP4 inside a Telegram callback or HTTP request.

The approval transaction must:

1. Confirm the review is pending and belongs to a task assigned to a channel owned by the approving user.
2. Mark the review and production task approved.
3. Insert one upload job for the review and assigned channel.
4. Return immediately with a queued confirmation.

The upload job has a unique constraint on `review_id`. Repeated approval callbacks return the existing job and never create another upload attempt.

Upload job states are:

- `queued`
- `uploading`
- `processing`
- `published`
- `failed_retryable`
- `failed_permanent`
- `auth_required`

The job stores attempt count, next-attempt time, error classification, resumable session information when safe to persist, YouTube video ID, public URL, and timestamps.

### Upload Worker

The `youtube-upload-worker` is a separate Docker service with access to PostgreSQL and the shared output volume. It claims jobs using database locking so multiple workers cannot process the same job concurrently.

For each job, the worker:

1. Revalidates channel ownership, assignment, review approval, metadata, and MP4 existence.
2. Decrypts the refresh token only in worker memory.
3. Obtains or refreshes a short-lived access token.
4. Starts or resumes a YouTube resumable upload.
5. Uploads the approved title, description, tags, language, category, and `privacyStatus=public`.
6. Uploads a custom thumbnail when a valid thumbnail artifact exists.
7. Stores the YouTube ID and URL before sending completion notifications.
8. Marks the related video and production task published.

The existing `UploadAgent` can provide low-level resumable upload behavior, but database lookup, metadata generation, and single-token assumptions must be separated from the new job orchestration. The worker must use already-approved metadata rather than generating new metadata during publishing.

## Security

- Refresh tokens are encrypted at rest with an application encryption key provided through environment configuration.
- Token ciphertext, access tokens, authorization codes, client secrets, and full callback queries are never logged.
- Ownership checks occur in SQL/service boundaries, not only in Telegram presentation code.
- OAuth state is random, short-lived, single-use, and stored server-side.
- OAuth callback URLs require HTTPS outside local tests.
- Disconnect revokes or deletes the stored credential and marks the channel unavailable.
- API responses expose channel identity and status, never credential material.
- Production startup validation fails when upload is enabled without OAuth client credentials or the encryption key.

## Retry and Failure Handling

Retryable failures include transient network errors, HTTP 429, and retryable YouTube 5xx responses. They use bounded exponential backoff with jitter and a maximum attempt count.

Permanent failures include missing files, invalid metadata, ownership mismatch, unsupported media, and non-retryable YouTube responses. Authentication failures mark the channel and job `auth_required` and send a reconnect button through Telegram.

The worker records enough structured error information for operations without storing secrets. It must persist the YouTube video ID as soon as YouTube returns it. If a local database update or notification fails after that point, recovery finalizes the existing job instead of uploading the file again.

## Telegram Experience

The bot adds button-driven flows for:

- `My channels`: list the user's connected channels and connection state.
- `Add channel`: issue the OAuth URL.
- `Disconnect`: remove access after explicit confirmation.
- `Create videos`: select one owned active channel, then configure count, duration, language, and layout.
- `Upload status`: show queued, active, failed, and recently published jobs for the user.

Review messages show the destination channel. Approve responds with `Upload queued` and the channel name. The worker subsequently sends `Uploading`, `Published`, or actionable failure notifications. Published notifications include the YouTube URL.

## Cloudflare Quick Tunnel

For temporary testing, `PUBLIC_BASE_URL` points to the active Quick Tunnel HTTPS URL. The exact OAuth callback URL must be registered in Google Cloud. Because Quick Tunnel URLs change after restart, the operator must update both values before reconnecting channels.

No channel credential is invalidated merely because the tunnel URL changes. The changed callback URL affects new connections and reconnections only. Production deployment should replace Quick Tunnel with a stable named tunnel without changing application code.

## Database Changes

Add tables for:

- `youtube_channels`
- `youtube_oauth_states`
- `youtube_upload_jobs`

Add the selected internal YouTube channel ID to `production_batches`, with task resolution through the batch relationship. Constraints and indexes must support ownership queries, active-channel listing, unique review jobs, job claiming, and retry scheduling.

Migrations must be additive and safe for existing batches. Historical batches may have no channel; they remain reviewable but cannot be uploaded until explicitly assigned through an administrative migration path outside this feature.

## Configuration

Add environment settings for:

- Google OAuth client ID and client secret.
- Exact OAuth callback path or URI.
- Token encryption key.
- YouTube upload enablement.
- Default privacy status fixed to `public` for this approved design.
- Upload retry and polling limits.

The Docker Compose stack adds `youtube-upload-worker` and mounts the existing output directory read-only where practical. The worker requires database access but does not require Redis for the initial database-backed queue.

## Testing

Unit tests cover:

- OAuth state creation, expiration, single use, and user binding.
- Token encryption and redaction.
- Channel ownership and cross-user denial.
- Channel selection validation.
- Approval idempotency.
- Upload error classification and retry timing.
- Access-token refresh behavior.

Integration tests cover:

- OAuth callback upserting a channel using mocked Google endpoints.
- Two users listing and selecting only their own channels.
- Approve creating exactly one upload job.
- Worker claiming, uploading, and publishing using a mocked resumable YouTube API.
- Recovery after YouTube returns a video ID but a later local operation fails.
- Authentication failure producing `auth_required` and a reconnect notification.

The production smoke procedure first uploads a small disposable video as Private to validate credentials and destination identity. After that explicit safety check passes, the configured application behavior remains Public as requested.

## Acceptance Criteria

- One Telegram user can connect and manage multiple YouTube channels.
- Another Telegram user cannot observe or use those channels through Telegram or direct API calls.
- A channel must be selected before a production batch is created.
- The selected channel remains attached through render, review, approval, and upload.
- Approving the same review repeatedly creates one upload job and at most one YouTube video.
- Successful uploads are Public and return a persisted YouTube ID and URL.
- Expired access tokens refresh without user interaction while the refresh token remains valid.
- Revoked or expired refresh tokens produce a reconnect flow instead of repeated upload attempts.
- Large MP4 files are streamed through resumable upload without passing through Telegram or n8n.
- The Docker stack runs the upload worker independently from the API and Telegram bot.

