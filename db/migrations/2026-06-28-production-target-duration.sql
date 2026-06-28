-- Telegram production target duration per batch.

ALTER TABLE production_batches
    ADD COLUMN IF NOT EXISTS target_duration INTEGER NOT NULL DEFAULT 60;
