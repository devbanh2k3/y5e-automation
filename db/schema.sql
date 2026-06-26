-- ============================================================
-- YouTube AI Automation — Full PostgreSQL Schema
-- ============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================
-- 1. reference_channels
-- ============================================================
CREATE TABLE IF NOT EXISTS reference_channels (
    id              SERIAL PRIMARY KEY,
    channel_url     TEXT NOT NULL UNIQUE,
    channel_name    TEXT NOT NULL,
    channel_id      TEXT,
    subscriber_count BIGINT DEFAULT 0,
    video_count     INTEGER DEFAULT 0,
    top_categories  JSONB DEFAULT '[]'::jsonb,
    title_patterns  JSONB DEFAULT '[]'::jsonb,
    content_style   TEXT DEFAULT '',
    thumbnail_style TEXT DEFAULT '',
    optimal_length  JSONB DEFAULT '{}'::jsonb,
    posting_schedule JSONB DEFAULT '{}'::jsonb,
    tag_strategy    JSONB DEFAULT '{}'::jsonb,
    topic_gaps      JSONB DEFAULT '[]'::jsonb,
    last_analyzed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reference_channels_channel_id ON reference_channels (channel_id);
CREATE INDEX idx_reference_channels_created_at ON reference_channels (created_at);

-- ============================================================
-- 2. reference_videos
-- ============================================================
CREATE TABLE IF NOT EXISTS reference_videos (
    id              SERIAL PRIMARY KEY,
    channel_id      INTEGER NOT NULL REFERENCES reference_channels(id) ON DELETE CASCADE,
    youtube_video_id TEXT NOT NULL,
    title           TEXT NOT NULL,
    views           BIGINT DEFAULT 0,
    likes           BIGINT DEFAULT 0,
    comments        BIGINT DEFAULT 0,
    duration_sec    INTEGER DEFAULT 0,
    published_at    TIMESTAMPTZ,
    description     TEXT DEFAULT '',
    tags            JSONB DEFAULT '[]'::jsonb,
    thumbnail_url   TEXT DEFAULT '',
    transcript      TEXT DEFAULT '',
    category_guess  TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_reference_videos_yt_id ON reference_videos (youtube_video_id);
CREATE INDEX idx_reference_videos_channel_id ON reference_videos (channel_id);
CREATE INDEX idx_reference_videos_views ON reference_videos (views DESC);
CREATE INDEX idx_reference_videos_published_at ON reference_videos (published_at DESC);
CREATE INDEX idx_reference_videos_category ON reference_videos (category_guess);

-- ============================================================
-- 3. topics
-- ============================================================
CREATE TABLE IF NOT EXISTS topics (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT 'vi',
    score           DECIMAL(6, 2) DEFAULT 0.0,
    score_details   JSONB DEFAULT '{}'::jsonb,
    inspired_by     INTEGER REFERENCES reference_channels(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (title, language)
);

CREATE INDEX idx_topics_status ON topics (status);
CREATE INDEX idx_topics_category ON topics (category);
CREATE INDEX idx_topics_score ON topics (score DESC);
CREATE INDEX idx_topics_inspired_by ON topics (inspired_by);
CREATE INDEX idx_topics_language ON topics (language);
CREATE INDEX idx_topics_created_at ON topics (created_at DESC);

-- ============================================================
-- 4. research_data
-- ============================================================
CREATE TABLE IF NOT EXISTS research_data (
    id              SERIAL PRIMARY KEY,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    item_name       TEXT NOT NULL,
    metrics         JSONB DEFAULT '{}'::jsonb,
    sources         JSONB DEFAULT '[]'::jsonb,
    verified        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_research_data_topic_id ON research_data (topic_id);
CREATE INDEX idx_research_data_verified ON research_data (verified);

-- ============================================================
-- 5. facts
-- ============================================================
CREATE TABLE IF NOT EXISTS facts (
    id              SERIAL PRIMARY KEY,
    research_id     INTEGER NOT NULL REFERENCES research_data(id) ON DELETE CASCADE,
    claim           TEXT NOT NULL,
    source_count    INTEGER DEFAULT 0,
    variance        DECIMAL(8, 4) DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'pending',
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_facts_research_id ON facts (research_id);
CREATE INDEX idx_facts_status ON facts (status);

-- ============================================================
-- 6. scripts
-- ============================================================
CREATE TABLE IF NOT EXISTS scripts (
    id              SERIAL PRIMARY KEY,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    language        TEXT NOT NULL DEFAULT 'vi',
    intro           TEXT DEFAULT '',
    sections        JSONB DEFAULT '[]'::jsonb,
    outro           TEXT DEFAULT '',
    word_count      INTEGER DEFAULT 0,
    quality_score   DECIMAL(5, 2) DEFAULT 0.0,
    grammar_ok      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scripts_topic_id ON scripts (topic_id);
CREATE INDEX idx_scripts_language ON scripts (language);

-- ============================================================
-- 7. assets
-- ============================================================
CREATE TABLE IF NOT EXISTS assets (
    id              SERIAL PRIMARY KEY,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    asset_type      TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    source_url      TEXT DEFAULT '',
    license         TEXT DEFAULT 'unknown',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_assets_topic_id ON assets (topic_id);
CREATE INDEX idx_assets_asset_type ON assets (asset_type);

-- ============================================================
-- 8. videos
-- ============================================================
CREATE TABLE IF NOT EXISTS videos (
    id              SERIAL PRIMARY KEY,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    file_path       TEXT DEFAULT '',
    resolution      TEXT NOT NULL DEFAULT '1920x1080',
    duration_sec    INTEGER DEFAULT 0,
    fps             INTEGER NOT NULL DEFAULT 30,
    codec           TEXT NOT NULL DEFAULT 'h264',
    youtube_id      TEXT,
    status          TEXT NOT NULL DEFAULT 'rendering',
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_videos_topic_id ON videos (topic_id);
CREATE INDEX idx_videos_status ON videos (status);
CREATE INDEX idx_videos_youtube_id ON videos (youtube_id);
CREATE INDEX idx_videos_published_at ON videos (published_at DESC);

-- ============================================================
-- 9. shorts
-- ============================================================
CREATE TABLE IF NOT EXISTS shorts (
    id              SERIAL PRIMARY KEY,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    file_path       TEXT DEFAULT '',
    start_sec       INTEGER DEFAULT 0,
    end_sec         INTEGER DEFAULT 0,
    youtube_id      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_shorts_video_id ON shorts (video_id);
CREATE INDEX idx_shorts_status ON shorts (status);

-- ============================================================
-- 10. analytics
-- ============================================================
CREATE TABLE IF NOT EXISTS analytics (
    id              SERIAL PRIMARY KEY,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    views           BIGINT NOT NULL DEFAULT 0,
    ctr             DECIMAL(6, 4) DEFAULT 0.0,
    avg_retention   DECIMAL(6, 4) DEFAULT 0.0,
    watch_time_hr   DECIMAL(10, 2) DEFAULT 0.0,
    subs_gained     INTEGER NOT NULL DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_analytics_video_id ON analytics (video_id);
CREATE INDEX idx_analytics_recorded_at ON analytics (recorded_at DESC);

-- ============================================================
-- 11. api_usage
-- ============================================================
CREATE TABLE IF NOT EXISTS api_usage (
    id              SERIAL PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    api_provider    TEXT NOT NULL,
    model_used      TEXT NOT NULL,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    is_fallback     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_usage_agent_name ON api_usage (agent_name);
CREATE INDEX idx_api_usage_created_at ON api_usage (created_at DESC);
CREATE INDEX idx_api_usage_provider ON api_usage (api_provider);

-- ============================================================
-- 12. pipeline_logs
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id              SERIAL PRIMARY KEY,
    topic_id        INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    agent_name      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipeline_logs_topic_id ON pipeline_logs (topic_id);
CREATE INDEX idx_pipeline_logs_agent_name ON pipeline_logs (agent_name);
CREATE INDEX idx_pipeline_logs_status ON pipeline_logs (status);
CREATE INDEX idx_pipeline_logs_created_at ON pipeline_logs (created_at DESC);
