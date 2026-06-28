-- Telegram Remote Production Control v1

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS telegram_users (
    telegram_user_id BIGINT PRIMARY KEY,
    username         TEXT DEFAULT '',
    role             TEXT NOT NULL DEFAULT 'producer',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_users_active ON telegram_users (is_active);
CREATE INDEX IF NOT EXISTS idx_telegram_users_role ON telegram_users (role);

CREATE TABLE IF NOT EXISTS production_batches (
    batch_id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_telegram_user_id   BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    category                 TEXT NOT NULL DEFAULT 'celebrity',
    language                 TEXT NOT NULL DEFAULT 'en',
    card_layout              TEXT NOT NULL DEFAULT 'flag_hero',
    target_duration          INTEGER NOT NULL DEFAULT 60,
    requested_count          INTEGER NOT NULL,
    completed_count          INTEGER NOT NULL DEFAULT 0,
    failed_count             INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'queued',
    manifest_path            TEXT DEFAULT '',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_production_batches_owner ON production_batches (owner_telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_production_batches_status ON production_batches (status);
CREATE INDEX IF NOT EXISTS idx_production_batches_created_at ON production_batches (created_at DESC);

CREATE TABLE IF NOT EXISTS production_tasks (
    task_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id                 UUID NOT NULL REFERENCES production_batches(batch_id) ON DELETE CASCADE,
    owner_telegram_user_id   BIGINT NOT NULL REFERENCES telegram_users(telegram_user_id),
    slot_index               INTEGER NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'queued',
    review_id                TEXT DEFAULT '',
    topic_id                 TEXT DEFAULT '',
    video_path               TEXT DEFAULT '',
    error                    TEXT DEFAULT '',
    attempt_count            INTEGER NOT NULL DEFAULT 0,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at               TIMESTAMPTZ,
    completed_at             TIMESTAMPTZ,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_production_tasks_owner_status ON production_tasks (owner_telegram_user_id, status);
CREATE INDEX IF NOT EXISTS idx_production_tasks_batch ON production_tasks (batch_id);
CREATE INDEX IF NOT EXISTS idx_production_tasks_status_created ON production_tasks (status, created_at);

CREATE TABLE IF NOT EXISTS production_user_scheduling (
    owner_telegram_user_id BIGINT PRIMARY KEY REFERENCES telegram_users(telegram_user_id),
    last_served_at         TIMESTAMPTZ
);
