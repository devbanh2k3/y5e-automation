from core.config import Settings


def test_development_allows_placeholder_credentials():
    settings = Settings(app_env="development")

    result = settings.validate_production_config()

    assert result.ok is True
    assert result.errors == {}


def test_production_rejects_placeholder_credentials():
    settings = Settings(
        app_env="production",
        primary_api_key="sk-CHANGE_ME",
        youtube_api_key="",
        database_url="postgresql://ytbot:ytbot@localhost:5432/youtube_automation",
        redis_url="redis://localhost:6379/0",
    )

    result = settings.validate_production_config()

    assert result.ok is False
    assert result.errors["primary_api_key"] == "must be set to a real value"
    assert result.errors["youtube_api_key"] == "must be set to a real value"
    assert "database_url" not in result.errors
    assert "redis_url" not in result.errors


def test_production_accepts_required_real_values():
    settings = Settings(
        app_env="production",
        primary_api_key="sk-real-production-key",
        youtube_api_key="AIza-real-youtube-key",
        database_url="postgresql://user:pass@db:5432/youtube_automation",
        redis_url="redis://redis:6379/0",
    )

    result = settings.validate_production_config()

    assert result.ok is True
    assert result.errors == {}


def test_upload_config_requires_oauth_and_encryption_when_enabled():
    settings = Settings(
        app_env="production",
        primary_api_key="sk-real-production-key",
        youtube_api_key="AIza-real-youtube-key",
        youtube_upload_enabled=True,
        youtube_oauth_client_id="",
        youtube_oauth_client_secret="",
        youtube_token_encryption_key="",
    )

    result = settings.validate_production_config()

    assert result.errors["youtube_oauth_client_id"] == "must be set to a real value"
    assert result.errors["youtube_oauth_client_secret"] == "must be set to a real value"
    assert result.errors["youtube_token_encryption_key"] == "must be set to a real value"


def test_resilient_card_settings_are_bounded():
    settings = Settings(
        card_minimum_ratio=1.5,
        card_content_repair_attempts=0,
        card_replacement_attempts=99,
    )

    assert settings.card_minimum_ratio == 1.0
    assert settings.card_content_repair_attempts == 1
    assert settings.card_replacement_attempts == 10
