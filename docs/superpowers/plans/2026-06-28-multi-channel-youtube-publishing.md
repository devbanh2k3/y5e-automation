# Multi-Channel YouTube Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each Telegram user connect multiple owned YouTube channels, select one per production batch, and publish an approved video publicly through an idempotent background upload queue.

**Architecture:** PostgreSQL stores tenant-owned channel identities, single-use OAuth state, immutable batch channel assignments, and upload jobs. Telegram initiates OAuth and channel selection; approval atomically queues one job; a dedicated Docker worker streams approved MP4 files through the YouTube resumable upload API using an encrypted per-channel refresh token.

**Tech Stack:** Python 3.12, FastAPI, asyncpg/PostgreSQL, httpx, cryptography/Fernet, Telegram Bot API, YouTube Data API v3, Docker Compose, pytest/pytest-asyncio.

---

## File Structure

- Create `db/migrations/2026-06-28-multi-channel-youtube-publishing.sql`: channel, OAuth-state, upload-job, and batch-assignment schema.
- Modify `core/config.py`: OAuth, encryption, callback, and upload worker settings.
- Modify `.env.example`: document required non-secret configuration names.
- Modify `requirements.txt`: add the token encryption dependency.
- Create `core/token_crypto.py`: encrypt and decrypt refresh tokens without logging plaintext.
- Create `core/youtube_channels.py`: tenant-scoped channel repository and connect-ticket/OAuth-state lifecycle.
- Create `services/youtube_oauth.py`: Google authorization URL, code exchange, token refresh, and authenticated channel lookup.
- Modify `api/main.py`: OAuth start/callback endpoints and minimal browser response.
- Create `services/telegram_channels.py`: channel list/add/select callback behavior and keyboards.
- Modify `scripts/telegram_remote_bot.py`: route channel callbacks separately from review callbacks.
- Modify `services/telegram_remote.py`: require explicit channel selection when creating a batch.
- Modify `core/production_tasks.py`: validate ownership and persist channel assignment.
- Create `core/youtube_upload_jobs.py`: atomic approval/job creation, claiming, retry, and terminal state updates.
- Modify `services/telegram_review_actions.py`: approve and enqueue exactly once for the assigned owner/channel.
- Create `services/youtube_upload_client.py`: per-channel token refresh and resumable upload using approved metadata.
- Create `scripts/process_youtube_upload_job.py`: background worker loop and notifications.
- Modify `docker-compose.yml`: add the upload worker and shared output mount.
- Modify `README.md`: operator setup, Quick Tunnel caveat, Google OAuth setup, and smoke procedure.
- Add focused tests alongside each unit in `tests/`.

### Task 1: Add the Multi-Tenant Publishing Schema

**Files:**
- Create: `db/migrations/2026-06-28-multi-channel-youtube-publishing.sql`
- Test: `tests/test_apply_db_migrations.py`

- [ ] **Step 1: Write the failing migration contract test**

```python
def test_multi_channel_youtube_migration_has_tenant_and_idempotency_constraints():
    sql = Path("db/migrations/2026-06-28-multi-channel-youtube-publishing.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS youtube_channels" in sql
    assert "UNIQUE (owner_telegram_user_id, external_channel_id)" in sql
    assert "CREATE TABLE IF NOT EXISTS youtube_oauth_states" in sql
    assert "CREATE TABLE IF NOT EXISTS youtube_upload_jobs" in sql
    assert "review_id TEXT NOT NULL UNIQUE" in sql
    assert "youtube_channel_id UUID" in sql
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_apply_db_migrations.py::test_multi_channel_youtube_migration_has_tenant_and_idempotency_constraints -v`

Expected: FAIL because the migration file does not exist.

- [ ] **Step 3: Add the additive migration**

```sql
CREATE TABLE IF NOT EXISTS youtube_channels (
    youtube_channel_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_telegram_user_id BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    external_channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    encrypted_refresh_token TEXT NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'auth_required', 'disconnected')),
    last_refreshed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_telegram_user_id, external_channel_id)
);

CREATE TABLE IF NOT EXISTS youtube_oauth_states (
    state_hash TEXT PRIMARY KEY,
    owner_telegram_user_id BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    purpose TEXT NOT NULL CHECK (purpose IN ('connect_ticket', 'oauth_state')),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE production_batches
    ADD COLUMN IF NOT EXISTS youtube_channel_id UUID REFERENCES youtube_channels(youtube_channel_id);

ALTER TABLE telegram_users
    ADD COLUMN IF NOT EXISTS selected_youtube_channel_id UUID
        REFERENCES youtube_channels(youtube_channel_id);

CREATE TABLE IF NOT EXISTS youtube_upload_jobs (
    upload_job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id TEXT NOT NULL UNIQUE,
    task_id UUID NOT NULL REFERENCES production_tasks(task_id),
    owner_telegram_user_id BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    youtube_channel_id UUID NOT NULL REFERENCES youtube_channels(youtube_channel_id),
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resumable_session_url TEXT DEFAULT '',
    youtube_video_id TEXT DEFAULT '',
    youtube_url TEXT DEFAULT '',
    error_code TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    started_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_youtube_channels_owner_status
    ON youtube_channels (owner_telegram_user_id, status);
CREATE INDEX IF NOT EXISTS idx_youtube_upload_jobs_claim
    ON youtube_upload_jobs (status, next_attempt_at, created_at);
```

- [ ] **Step 4: Verify the migration contract and apply it in Docker**

Run: `pytest tests/test_apply_db_migrations.py -v && docker compose run --rm db-migrate`

Expected: tests PASS and migration runner exits 0.

- [ ] **Step 5: Commit the schema**

```bash
git add db/migrations/2026-06-28-multi-channel-youtube-publishing.sql tests/test_apply_db_migrations.py
git commit -m "feat: add multi-channel publishing schema"
```

### Task 2: Add Secure Publishing Configuration and Token Encryption

**Files:**
- Modify: `core/config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`
- Create: `core/token_crypto.py`
- Create: `tests/test_token_crypto.py`
- Modify: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing encryption and production-validation tests**

```python
def test_refresh_token_round_trip(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    ciphertext = encrypt_secret("refresh-token")
    assert "refresh-token" not in ciphertext
    assert decrypt_secret(ciphertext) == "refresh-token"


def test_upload_config_requires_oauth_and_encryption_when_enabled(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("YOUTUBE_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    result = get_settings().validate_production_config()
    assert "youtube_oauth_client_id" in result.errors
    assert "youtube_token_encryption_key" in result.errors
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_token_crypto.py tests/test_config_validation.py -v`

Expected: FAIL because settings and `core.token_crypto` are absent.

- [ ] **Step 3: Add settings and the focused encryption module**

```python
# core/config.py fields
youtube_upload_enabled: bool = False
youtube_oauth_client_id: str = ""
youtube_oauth_client_secret: str = ""
youtube_oauth_callback_path: str = "/api/youtube/oauth/callback"
youtube_token_encryption_key: str = ""
youtube_upload_max_attempts: int = 5
youtube_upload_poll_seconds: float = 5.0
```

```python
# core/token_crypto.py
from cryptography.fernet import Fernet, InvalidToken
from core.config import get_settings

class TokenCryptoError(RuntimeError):
    pass

def _fernet() -> Fernet:
    key = get_settings().youtube_token_encryption_key.strip().encode()
    if not key:
        raise TokenCryptoError("YOUTUBE_TOKEN_ENCRYPTION_KEY is required")
    return Fernet(key)

def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenCryptoError("encrypted token cannot be decrypted") from exc
```

Add `cryptography>=44.0.0,<46.0` to `requirements.txt`, document the new variables in `.env.example`, and extend production validation only when `youtube_upload_enabled` is true.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_token_crypto.py tests/test_config_validation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit configuration and encryption**

```bash
git add core/config.py core/token_crypto.py .env.example requirements.txt tests/test_token_crypto.py tests/test_config_validation.py
git commit -m "feat: secure YouTube channel credentials"
```

### Task 3: Implement Tenant-Scoped Channel and OAuth-State Storage

**Files:**
- Create: `core/youtube_channels.py`
- Create: `tests/test_youtube_channels.py`

- [ ] **Step 1: Write failing ownership and single-use state tests**

```python
@pytest.mark.asyncio
async def test_get_owned_channel_rejects_another_owner(monkeypatch):
    async def fake_fetchrow(query, *args):
        return None
    monkeypatch.setattr(youtube_channels, "fetchrow", fake_fetchrow)
    with pytest.raises(ChannelAccessError):
        await youtube_channels.get_owned_channel("channel-1", owner_telegram_user_id=222)


@pytest.mark.asyncio
async def test_consume_state_is_single_use(monkeypatch):
    calls = []
    async def fake_fetchrow(query, *args):
        calls.append((query, args))
        return {"owner_telegram_user_id": 111} if len(calls) == 1 else None
    monkeypatch.setattr(youtube_channels, "fetchrow", fake_fetchrow)
    assert await youtube_channels.consume_oauth_token("raw", purpose="oauth_state") == 111
    with pytest.raises(OAuthStateError):
        await youtube_channels.consume_oauth_token("raw", purpose="oauth_state")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_youtube_channels.py -v`

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Implement explicit repository boundaries**

```python
class ChannelAccessError(PermissionError):
    pass

class OAuthStateError(ValueError):
    pass

def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()

async def get_owned_channel(channel_id: str, *, owner_telegram_user_id: int) -> dict[str, Any]:
    row = await fetchrow(
        """SELECT * FROM youtube_channels
           WHERE youtube_channel_id = $1::uuid
             AND owner_telegram_user_id = $2""",
        channel_id, owner_telegram_user_id,
    )
    if not row:
        raise ChannelAccessError("YouTube channel is unavailable")
    return row

async def issue_oauth_token(*, owner_telegram_user_id: int, purpose: str, ttl_seconds: int = 600) -> str:
    raw = secrets.token_urlsafe(32)
    await execute(
        """INSERT INTO youtube_oauth_states (state_hash, owner_telegram_user_id, purpose, expires_at)
           VALUES ($1, $2, $3, NOW() + ($4 * INTERVAL '1 second'))""",
        _token_hash(raw), owner_telegram_user_id, purpose, ttl_seconds,
    )
    return raw

async def consume_oauth_token(raw: str, *, purpose: str) -> int:
    row = await fetchrow(
        """UPDATE youtube_oauth_states SET consumed_at = NOW()
           WHERE state_hash = $1 AND purpose = $2 AND consumed_at IS NULL AND expires_at > NOW()
           RETURNING owner_telegram_user_id""",
        _token_hash(raw), purpose,
    )
    if not row:
        raise OAuthStateError("OAuth link is invalid, expired, or already used")
    return int(row["owner_telegram_user_id"])
```

Also implement `list_owned_channels`, `upsert_owned_channel`, `mark_auth_required`, and `disconnect_owned_channel`; every channel ID lookup includes `owner_telegram_user_id`.

- [ ] **Step 4: Run repository tests**

Run: `pytest tests/test_youtube_channels.py -v`

Expected: PASS.

- [ ] **Step 5: Commit repository behavior**

```bash
git add core/youtube_channels.py tests/test_youtube_channels.py
git commit -m "feat: add tenant-scoped YouTube channels"
```

### Task 4: Implement Google OAuth and API Callback

**Files:**
- Create: `services/youtube_oauth.py`
- Modify: `api/main.py`
- Create: `tests/test_youtube_oauth.py`
- Create: `tests/test_api_youtube_oauth.py`

- [ ] **Step 1: Write failing URL, callback, and token-redaction tests**

```python
def test_authorization_url_requests_offline_upload_access():
    url = build_authorization_url(state="state-1", redirect_uri="https://x.test/api/youtube/oauth/callback")
    query = parse_qs(urlparse(url).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/youtube.upload" in query["scope"][0]


@pytest.mark.asyncio
async def test_callback_consumes_state_and_upserts_authenticated_channel(monkeypatch):
    # Mock state consumption, Google token exchange, channels.list, and repository upsert.
    response = await oauth_callback(code="code-1", state="state-1")
    assert response["external_channel_id"] == "UC123"
    assert "refresh_token" not in response
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_youtube_oauth.py tests/test_api_youtube_oauth.py -v`

Expected: FAIL because OAuth service and routes are absent.

- [ ] **Step 3: Implement OAuth with minimum scopes**

```python
YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)

def callback_uri() -> str:
    settings = get_settings()
    return f"{settings.public_base_url.rstrip('/')}{settings.youtube_oauth_callback_path}"

def build_authorization_url(*, state: str, redirect_uri: str) -> str:
    params = {
        "client_id": get_settings().youtube_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
```

Implement `/api/youtube/oauth/start?ticket=...` to consume a connect ticket, issue an OAuth state, and redirect to Google. Implement `/api/youtube/oauth/callback` to consume state, exchange code, call `channels.list(part=snippet,mine=true)`, encrypt the refresh token, upsert the channel, notify the owner, and return a small HTML success page. Never include token response bodies in errors or logs.

- [ ] **Step 4: Run OAuth tests**

Run: `pytest tests/test_youtube_oauth.py tests/test_api_youtube_oauth.py -v`

Expected: PASS, including state replay returning HTTP 400.

- [ ] **Step 5: Commit OAuth flow**

```bash
git add services/youtube_oauth.py api/main.py tests/test_youtube_oauth.py tests/test_api_youtube_oauth.py
git commit -m "feat: connect YouTube channels with OAuth"
```

### Task 5: Add Telegram Channel Management and Explicit Batch Selection

**Files:**
- Create: `services/telegram_channels.py`
- Modify: `scripts/telegram_remote_bot.py`
- Modify: `services/telegram_remote.py`
- Modify: `core/production_tasks.py`
- Create: `tests/test_telegram_channels.py`
- Modify: `tests/test_telegram_remote.py`
- Modify: `tests/test_telegram_remote_bot.py`
- Modify: `tests/test_production_tasks.py`

- [ ] **Step 1: Write failing channel button and batch ownership tests**

```python
@pytest.mark.asyncio
async def test_create_requires_explicit_owned_channel(monkeypatch):
    response = await handle_telegram_command(telegram_user_id=111, text="/create 1")
    assert "Select a YouTube channel" in response


@pytest.mark.asyncio
async def test_create_batch_rejects_channel_owned_by_another_user(monkeypatch):
    monkeypatch.setattr(production_tasks, "fetchrow", AsyncMock(return_value=None))
    with pytest.raises(PermissionError):
        await production_tasks.create_production_batch(
            owner_telegram_user_id=111,
            youtube_channel_id="channel-of-user-222",
            requested_count=1,
        )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_telegram_channels.py tests/test_telegram_remote.py tests/test_telegram_remote_bot.py tests/test_production_tasks.py -v`

Expected: FAIL because channel callbacks and batch assignment are absent.

- [ ] **Step 3: Add button-driven channel management**

```python
def build_channel_keyboard(channels: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [[{
        "text": channel["title"],
        "callback_data": f"yt:select:{channel['youtube_channel_id']}",
    }] for channel in channels if channel["status"] == "active"]
    rows.append([{"text": "Add channel", "callback_data": "yt:add"}])
    return {"inline_keyboard": rows}
```

Route `yt:*` callbacks to `handle_channel_callback`. `yt:add` issues a connect ticket and returns an HTTPS URL button to `/api/youtube/oauth/start`. `yt:select:<id>` verifies ownership and stores a short-lived per-user create selection in PostgreSQL; the next `/create` consumes that selection.

Modify `create_production_batch` to require `youtube_channel_id`, validate owner plus `status='active'`, insert it into `production_batches`, and include channel title in its return value. Include channel identity in `claim_next_fair_task`, batch listings, and render completion notifications.

- [ ] **Step 4: Run channel-selection tests**

Run: `pytest tests/test_telegram_channels.py tests/test_telegram_remote.py tests/test_telegram_remote_bot.py tests/test_production_tasks.py -v`

Expected: PASS; cross-owner channel selection is denied.

- [ ] **Step 5: Commit Telegram channel selection**

```bash
git add services/telegram_channels.py scripts/telegram_remote_bot.py services/telegram_remote.py core/production_tasks.py tests/test_telegram_channels.py tests/test_telegram_remote.py tests/test_telegram_remote_bot.py tests/test_production_tasks.py
git commit -m "feat: select owned YouTube channel per batch"
```

### Task 6: Add Atomic Approval and Idempotent Upload Jobs

**Files:**
- Modify: `core/database.py`
- Create: `core/youtube_upload_jobs.py`
- Modify: `services/telegram_review_actions.py`
- Create: `tests/test_youtube_upload_jobs.py`
- Modify: `tests/test_telegram_review_actions.py`

- [ ] **Step 1: Write failing idempotency and ownership tests**

```python
@pytest.mark.asyncio
async def test_approve_and_enqueue_returns_existing_job_on_repeat(monkeypatch):
    first = await approve_and_enqueue(review_id="review-1", owner_telegram_user_id=111)
    second = await approve_and_enqueue(review_id="review-1", owner_telegram_user_id=111)
    assert first["upload_job_id"] == second["upload_job_id"]


@pytest.mark.asyncio
async def test_approve_cannot_enqueue_another_users_review(monkeypatch):
    with pytest.raises(PermissionError):
        await approve_and_enqueue(review_id="review-user-222", owner_telegram_user_id=111)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_youtube_upload_jobs.py tests/test_telegram_review_actions.py -v`

Expected: FAIL because the upload job service does not exist.

- [ ] **Step 3: Add a database transaction helper and approval service**

```python
@asynccontextmanager
async def transaction():
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            yield connection
```

```python
async def approve_and_enqueue(*, review_id: str, owner_telegram_user_id: int) -> dict[str, Any]:
    ownership = await fetchrow(
        """SELECT t.task_id
           FROM production_tasks t
           JOIN production_batches b ON b.batch_id = t.batch_id
           JOIN youtube_channels c ON c.youtube_channel_id = b.youtube_channel_id
           WHERE t.review_id = $1 AND t.owner_telegram_user_id = $2
             AND c.owner_telegram_user_id = $2""",
        review_id, owner_telegram_user_id,
    )
    if not ownership:
        raise PermissionError("Review is unavailable")

    await approve_review(review_id, notes="approved from Telegram")

    async with transaction() as conn:
        task = await conn.fetchrow(
            """SELECT t.task_id, t.status, b.youtube_channel_id
               FROM production_tasks t
               JOIN production_batches b ON b.batch_id = t.batch_id
               JOIN youtube_channels c ON c.youtube_channel_id = b.youtube_channel_id
               WHERE t.review_id = $1 AND t.owner_telegram_user_id = $2
                 AND c.owner_telegram_user_id = $2
               FOR UPDATE""",
            review_id, owner_telegram_user_id,
        )
        if not task:
            raise PermissionError("Review is unavailable")
        job = await conn.fetchrow(
            """INSERT INTO youtube_upload_jobs
                   (review_id, task_id, owner_telegram_user_id, youtube_channel_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (review_id) DO UPDATE SET review_id = EXCLUDED.review_id
               RETURNING upload_job_id::text, status""",
            review_id, task["task_id"], owner_telegram_user_id, task["youtube_channel_id"],
        )
        await conn.execute(
            "UPDATE production_tasks SET status='approved', updated_at=NOW() WHERE task_id=$1",
            task["task_id"],
        )
    return dict(job)
```

Keep the JSON review transition idempotent. Ownership is checked before the review artifact changes, and the upload job is inserted only after the approved artifact is durable. If the database transaction fails, repeating Approve reuses the already-approved artifact and creates the missing job. Update Telegram approval to call this service and reply with the existing or newly queued job ID.

- [ ] **Step 4: Run approval tests**

Run: `pytest tests/test_youtube_upload_jobs.py tests/test_telegram_review_actions.py tests/test_reviews.py -v`

Expected: PASS.

- [ ] **Step 5: Commit approval queue integration**

```bash
git add core/database.py core/youtube_upload_jobs.py services/telegram_review_actions.py tests/test_youtube_upload_jobs.py tests/test_telegram_review_actions.py
git commit -m "feat: queue approved videos for upload"
```

### Task 7: Extract a Per-Channel YouTube Upload Client

**Files:**
- Create: `services/youtube_upload_client.py`
- Modify: `agents/upload_agent.py`
- Create: `tests/test_youtube_upload_client.py`

- [ ] **Step 1: Write failing refresh, approved-metadata, and resumable tests**

```python
@pytest.mark.asyncio
async def test_refresh_uses_decrypted_channel_token(monkeypatch):
    token = await client.refresh_access_token(encrypted_refresh_token="ciphertext")
    assert token == "access-1"


@pytest.mark.asyncio
async def test_upload_uses_public_status_and_supplied_metadata(tmp_path, mock_transport):
    result = await client.upload_video(
        access_token="access-1",
        video_path=tmp_path / "video.mp4",
        metadata={"title": "Approved", "description": "Approved body", "tags": ["celebrity"]},
        language="en",
    )
    assert result.youtube_video_id == "yt-123"
    assert mock_transport.initiation_json["status"]["privacyStatus"] == "public"
    assert mock_transport.initiation_json["snippet"]["title"] == "Approved"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_youtube_upload_client.py -v`

Expected: FAIL because the per-channel client does not exist.

- [ ] **Step 3: Extract low-level upload behavior**

```python
@dataclass(frozen=True)
class UploadResult:
    youtube_video_id: str
    youtube_url: str

class YouTubeAuthRequired(UploadError):
    pass

class YouTubeRetryableError(UploadError):
    pass

async def refresh_access_token(self, *, encrypted_refresh_token: str) -> str:
    response = await self.http.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": self.settings.youtube_oauth_client_id,
            "client_secret": self.settings.youtube_oauth_client_secret,
            "refresh_token": decrypt_secret(encrypted_refresh_token),
            "grant_type": "refresh_token",
        },
    )
    if response.status_code == 400 and response.json().get("error") == "invalid_grant":
        raise YouTubeAuthRequired("YouTube authorization must be renewed")
    if response.status_code == 429 or response.status_code >= 500:
        raise YouTubeRetryableError("YouTube token endpoint is temporarily unavailable")
    response.raise_for_status()
    return str(response.json()["access_token"])
```

Move reusable resumable upload and thumbnail methods from `UploadAgent` into this client. Accept metadata as an argument; do not call AI or query scripts/topics. Stream chunks from disk, classify 429/5xx as retryable, classify `invalid_grant` as auth required, and return the YouTube ID immediately after completion. Keep `UploadAgent` delegating to the client for backward compatibility until the legacy pipeline is retired.

- [ ] **Step 4: Run upload client and legacy agent tests**

Run: `pytest tests/test_youtube_upload_client.py tests/test_pipeline_smoke.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the upload client**

```bash
git add services/youtube_upload_client.py agents/upload_agent.py tests/test_youtube_upload_client.py
git commit -m "refactor: extract per-channel YouTube upload client"
```

### Task 8: Implement Upload Job Claiming, Recovery, and Worker Notifications

**Files:**
- Modify: `core/youtube_upload_jobs.py`
- Create: `scripts/process_youtube_upload_job.py`
- Modify: `services/telegram_notifications.py`
- Create: `tests/test_process_youtube_upload_job.py`
- Modify: `tests/test_youtube_upload_jobs.py`

- [ ] **Step 1: Write failing claim, recovery, and failure-classification tests**

```python
@pytest.mark.asyncio
async def test_worker_persists_youtube_id_before_notification(monkeypatch):
    events = []
    monkeypatch.setattr(worker, "mark_uploaded", AsyncMock(side_effect=lambda **kw: events.append("stored")))
    monkeypatch.setattr(worker, "notify_published", AsyncMock(side_effect=lambda **kw: events.append("notified")))
    await worker.process_job(JOB)
    assert events == ["stored", "notified"]


@pytest.mark.asyncio
async def test_auth_failure_marks_channel_and_job_without_retry(monkeypatch):
    monkeypatch.setattr(worker.client, "refresh_access_token", AsyncMock(side_effect=YouTubeAuthRequired("renew")))
    await worker.process_job(JOB)
    assert mark_auth_required.await_count == 1
    assert reschedule.await_count == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_process_youtube_upload_job.py tests/test_youtube_upload_jobs.py -v`

Expected: FAIL because worker claiming and processing are absent.

- [ ] **Step 3: Implement lock-safe claiming and worker orchestration**

```python
async def claim_next_upload_job() -> dict[str, Any] | None:
    return await fetchrow(
        """UPDATE youtube_upload_jobs SET
               status='uploading', attempt_count=attempt_count+1,
               started_at=COALESCE(started_at, NOW()), updated_at=NOW()
           WHERE upload_job_id = (
               SELECT upload_job_id FROM youtube_upload_jobs
               WHERE status IN ('queued', 'failed_retryable')
                 AND next_attempt_at <= NOW()
               ORDER BY created_at
               FOR UPDATE SKIP LOCKED LIMIT 1
           )
           RETURNING *"""
    )
```

`process_job` loads the review JSON and channel row, checks that the review is approved, uses only `review['youtube']` metadata, uploads, stores YouTube identity, marks the video/task/job published, then notifies Telegram. If `youtube_video_id` is already stored, skip upload and finalize local state. Retryable failures use `min(900, 2 ** attempt_count * 15)` seconds plus jitter; auth failures mark both channel and job `auth_required`; permanent failures retain a redacted message.

The CLI supports `--once`, `--loop`, and `--idle-sleep`, initializes/closes the database cleanly, and handles SIGTERM so Docker shutdown does not abandon a claimed job silently.

- [ ] **Step 4: Run worker tests**

Run: `pytest tests/test_process_youtube_upload_job.py tests/test_youtube_upload_jobs.py tests/test_telegram_notifications.py -v`

Expected: PASS.

- [ ] **Step 5: Commit worker behavior**

```bash
git add core/youtube_upload_jobs.py scripts/process_youtube_upload_job.py services/telegram_notifications.py tests/test_process_youtube_upload_job.py tests/test_youtube_upload_jobs.py tests/test_telegram_notifications.py
git commit -m "feat: process YouTube upload jobs reliably"
```

### Task 9: Add Upload Status and Disconnect Controls to Telegram

**Files:**
- Modify: `services/telegram_channels.py`
- Modify: `services/telegram_remote.py`
- Modify: `scripts/telegram_remote_bot.py`
- Modify: `tests/test_telegram_channels.py`
- Modify: `tests/test_telegram_remote.py`

- [ ] **Step 1: Write failing status and cross-owner disconnect tests**

```python
@pytest.mark.asyncio
async def test_upload_status_lists_only_owner_jobs(monkeypatch):
    monkeypatch.setattr(youtube_upload_jobs, "list_owner_jobs", AsyncMock(return_value=[{"status": "published"}]))
    text = await handle_telegram_command(telegram_user_id=111, text="/uploads")
    assert "Published" in text


@pytest.mark.asyncio
async def test_disconnect_callback_cannot_disconnect_another_users_channel(monkeypatch):
    result = await handle_channel_callback(telegram_user_id=111, data="yt:disconnect:channel-user-222")
    assert "unavailable" in result.text.lower()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_telegram_channels.py tests/test_telegram_remote.py -v`

Expected: FAIL because status/disconnect behavior is absent.

- [ ] **Step 3: Implement owner-filtered operational controls**

Add `/channels` and `/uploads` commands and corresponding menu buttons. List channel title/status without credentials. Require a second `yt:disconnect_confirm:<id>` callback, make a best-effort call to Google's token revocation endpoint, erase the stored encrypted token, and mark the channel disconnected. Upload status shows the most recent ten jobs with channel title, state, short error code, and YouTube URL when published. `auth_required` rows include a reconnect button that starts a new connect-ticket flow.

```python
async def list_owner_jobs(owner_telegram_user_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
    return await fetch(
        """SELECT j.status, j.youtube_url, j.error_code, c.title
           FROM youtube_upload_jobs j
           JOIN youtube_channels c ON c.youtube_channel_id=j.youtube_channel_id
           WHERE j.owner_telegram_user_id=$1
           ORDER BY j.created_at DESC LIMIT $2""",
        owner_telegram_user_id, max(1, min(limit, 50)),
    )
```

- [ ] **Step 4: Run Telegram tests**

Run: `pytest tests/test_telegram_channels.py tests/test_telegram_remote.py tests/test_telegram_remote_bot.py -v`

Expected: PASS.

- [ ] **Step 5: Commit operational controls**

```bash
git add services/telegram_channels.py services/telegram_remote.py scripts/telegram_remote_bot.py core/youtube_upload_jobs.py tests/test_telegram_channels.py tests/test_telegram_remote.py tests/test_telegram_remote_bot.py
git commit -m "feat: manage YouTube publishing from Telegram"
```

### Task 10: Wire Docker Runtime and Production Documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `README.md`
- Modify: `tests/test_docker_runtime_contract.py`

- [ ] **Step 1: Write the failing Docker service contract**

```python
def test_compose_runs_youtube_upload_worker_with_shared_output():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    worker = compose["services"]["youtube-upload-worker"]
    assert worker["command"][:2] == ["python", "scripts/process_youtube_upload_job.py"]
    assert "./output:/app/output" in worker["volumes"]
    assert worker["depends_on"]["db-migrate"]["condition"] == "service_completed_successfully"
```

- [ ] **Step 2: Run the contract test and verify failure**

Run: `pytest tests/test_docker_runtime_contract.py::test_compose_runs_youtube_upload_worker_with_shared_output -v`

Expected: FAIL because the service is absent.

- [ ] **Step 3: Add the worker service and operator runbook**

```yaml
youtube-upload-worker:
  image: youtube_ai_automation-app:latest
  restart: unless-stopped
  command: ["python", "scripts/process_youtube_upload_job.py", "--loop", "--idle-sleep", "5"]
  env_file: [.env]
  environment:
    DATABASE_URL: postgresql://ytbot:ytbot@postgres:5432/youtube_automation
  volumes:
    - ./output:/app/output
  depends_on:
    db-migrate:
      condition: service_completed_successfully
```

Document how to generate a Fernet key, enable YouTube Data API v3, configure an External OAuth consent screen and test users, register the exact Quick Tunnel callback, set upload variables, rebuild, apply migrations, connect a channel, and inspect worker logs. Explicitly state that a restarted Quick Tunnel requires updating `PUBLIC_BASE_URL` and Google redirect URI.

- [ ] **Step 4: Validate Compose and documentation tests**

Run: `docker compose config --quiet && pytest tests/test_docker_runtime_contract.py -v`

Expected: both commands exit 0.

- [ ] **Step 5: Commit runtime wiring**

```bash
git add docker-compose.yml Dockerfile README.md tests/test_docker_runtime_contract.py
git commit -m "ops: run YouTube upload worker in Docker"
```

### Task 11: End-to-End Safety and Regression Verification

**Files:**
- Create: `tests/test_multi_channel_publishing_flow.py`
- Modify: `README.md`

- [ ] **Step 1: Add an integration test for two-user isolation and duplicate approval**

```python
@pytest.mark.asyncio
async def test_two_users_publish_only_to_owned_selected_channels(test_db, mocked_youtube):
    alice_channel = await seed_channel(owner=111, external_id="UC_ALICE")
    bob_channel = await seed_channel(owner=222, external_id="UC_BOB")
    batch = await create_production_batch(
        owner_telegram_user_id=111,
        youtube_channel_id=alice_channel,
        requested_count=1,
    )
    review_id = await seed_pending_review(batch=batch)

    with pytest.raises(PermissionError):
        await approve_and_enqueue(review_id=review_id, owner_telegram_user_id=222)

    first = await approve_and_enqueue(review_id=review_id, owner_telegram_user_id=111)
    second = await approve_and_enqueue(review_id=review_id, owner_telegram_user_id=111)
    assert first["upload_job_id"] == second["upload_job_id"]
    await run_one_upload_job()
    assert mocked_youtube.upload_count == 1
    assert mocked_youtube.channel == "UC_ALICE"
    assert mocked_youtube.privacy_status == "public"
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/test_multi_channel_publishing_flow.py -v`

Expected: PASS with one mocked upload to Alice's channel.

- [ ] **Step 3: Run the complete automated suite**

Run: `pytest -q`

Expected: all tests PASS with no network calls to Google or YouTube.

- [ ] **Step 4: Run Docker smoke checks without publishing**

Run: `docker compose build api telegram-bot youtube-upload-worker && docker compose up -d db-migrate api telegram-bot youtube-upload-worker && docker compose ps && docker compose logs --tail=100 youtube-upload-worker`

Expected: migration completes, services remain running, API is healthy, and worker polls without credential leakage.

- [ ] **Step 5: Perform the controlled real-channel smoke**

Set `YOUTUBE_UPLOAD_ENABLED=false`, connect the intended test channel through Telegram, and confirm `/channels` reports the exact title and channel ID. Temporarily run one disposable upload with privacy overridden to Private from an operator-only smoke command, verify the destination in YouTube Studio, delete the disposable upload, then restore the approved production setting `public` and enable the upload worker.

Expected: the disposable video appears only on the selected test channel; no production review is consumed.

- [ ] **Step 6: Commit integration coverage and runbook corrections**

```bash
git add tests/test_multi_channel_publishing_flow.py README.md
git commit -m "test: verify multi-channel publishing isolation"
```

## Completion Gate

- [ ] Every automated test passes.
- [ ] Docker Compose validates and the worker shuts down cleanly.
- [ ] No token, authorization code, client secret, or callback query is present in logs.
- [ ] Two-user isolation and repeated-approval idempotency are proven by tests.
- [ ] A controlled Private smoke confirms the real destination channel before Public publishing is enabled.
- [ ] Quick Tunnel limitations and the migration path to a stable tunnel are documented.
