-- Multi-channel YouTube publishing foundation.

CREATE TABLE IF NOT EXISTS youtube_channels (
    youtube_channel_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_telegram_user_id      BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    external_channel_id         TEXT NOT NULL,
    title                       TEXT NOT NULL,
    encrypted_refresh_token     TEXT NOT NULL,
    scopes                      TEXT[] NOT NULL DEFAULT '{}',
    status                      TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'auth_required', 'disconnected')),
    last_refreshed_at           TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_telegram_user_id, external_channel_id)
);

CREATE INDEX IF NOT EXISTS idx_youtube_channels_owner_status
    ON youtube_channels (owner_telegram_user_id, status);

CREATE TABLE IF NOT EXISTS youtube_oauth_states (
    state_hash                  TEXT PRIMARY KEY,
    owner_telegram_user_id      BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    purpose                     TEXT NOT NULL CHECK (purpose IN ('connect_ticket', 'oauth_state')),
    expires_at                  TIMESTAMPTZ NOT NULL,
    consumed_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_youtube_oauth_states_expiry
    ON youtube_oauth_states (expires_at)
    WHERE consumed_at IS NULL;

ALTER TABLE telegram_users
    ADD COLUMN IF NOT EXISTS selected_youtube_channel_id UUID
    REFERENCES youtube_channels(youtube_channel_id);

ALTER TABLE production_batches
    ADD COLUMN IF NOT EXISTS youtube_channel_id UUID
    REFERENCES youtube_channels(youtube_channel_id);

CREATE TABLE IF NOT EXISTS youtube_upload_jobs (
    upload_job_id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id                   TEXT NOT NULL UNIQUE,
    task_id                     UUID NOT NULL REFERENCES production_tasks(task_id),
    owner_telegram_user_id      BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    youtube_channel_id          UUID NOT NULL REFERENCES youtube_channels(youtube_channel_id),
    status                      TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN (
                                    'queued',
                                    'uploading',
                                    'processing',
                                    'published',
                                    'failed_retryable',
                                    'failed_permanent',
                                    'auth_required'
                                )),
    attempt_count               INTEGER NOT NULL DEFAULT 0,
    max_attempts                INTEGER NOT NULL DEFAULT 5,
    next_attempt_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resumable_session_url       TEXT NOT NULL DEFAULT '',
    youtube_video_id            TEXT NOT NULL DEFAULT '',
    youtube_url                 TEXT NOT NULL DEFAULT '',
    error_code                  TEXT NOT NULL DEFAULT '',
    error_message               TEXT NOT NULL DEFAULT '',
    started_at                  TIMESTAMPTZ,
    published_at                TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_youtube_upload_jobs_claim
    ON youtube_upload_jobs (status, next_attempt_at, created_at);

CREATE INDEX IF NOT EXISTS idx_youtube_upload_jobs_owner_created
    ON youtube_upload_jobs (owner_telegram_user_id, created_at DESC);
