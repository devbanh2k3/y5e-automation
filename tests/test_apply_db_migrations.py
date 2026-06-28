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
