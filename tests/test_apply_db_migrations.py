from pathlib import Path


def test_migration_files_keep_chat_routing_after_telegram_base() -> None:
    from scripts import apply_db_migrations

    paths = [
        Path("2026-06-28-telegram-chat-routing.sql"),
        Path("2026-06-28-production-target-duration.sql"),
        Path("2026-06-28-telegram-remote-production.sql"),
    ]

    ordered = sorted(paths, key=apply_db_migrations.migration_sort_key)

    assert [path.name for path in ordered] == [
        "2026-06-28-telegram-remote-production.sql",
        "2026-06-28-production-target-duration.sql",
        "2026-06-28-telegram-chat-routing.sql",
    ]


def test_migration_runner_uses_schema_migrations_table() -> None:
    source = Path("scripts/apply_db_migrations.py").read_text()

    assert "argparse.ArgumentParser" in source
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in source
    assert "SELECT 1 FROM schema_migrations WHERE filename = $1" in source
    assert "INSERT INTO schema_migrations" in source


def test_multi_channel_youtube_migration_has_tenant_and_idempotency_constraints() -> None:
    sql = Path(
        "db/migrations/2026-06-28-multi-channel-youtube-publishing.sql"
    ).read_text()

    assert "CREATE TABLE IF NOT EXISTS youtube_channels" in sql
    assert "UNIQUE (owner_telegram_user_id, external_channel_id)" in sql
    assert "CREATE TABLE IF NOT EXISTS youtube_oauth_states" in sql
    assert "CREATE TABLE IF NOT EXISTS youtube_upload_jobs" in sql
    assert "review_id" in sql and "UNIQUE" in sql
    assert "youtube_channel_id UUID" in sql
