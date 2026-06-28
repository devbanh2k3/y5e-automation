-- Telegram per-user chat routing.

ALTER TABLE telegram_users
    ADD COLUMN IF NOT EXISTS chat_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_telegram_users_chat_id ON telegram_users (chat_id);
