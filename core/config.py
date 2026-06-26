"""Centralized configuration loaded from environment variables."""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel


class ConfigValidationResult(BaseModel):
    """Structured production configuration validation result."""

    ok: bool
    errors: dict[str, str]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime mode ──────────────────────────────────────────
    app_env: str = "development"

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql://ytbot:ytbot@localhost:5432/youtube_automation"

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Primary AI endpoint (OpenAI-compatible) ───────────────
    primary_api_base: str = "https://api.openai.com/v1"
    primary_api_key: str = "sk-CHANGE_ME"
    primary_model: str = "gemini-3-flash-preview"

    # ── Fallback AI endpoint ──────────────────────────────────
    fallback_api_base: str = "https://api.openai.com/v1"
    fallback_api_key: str = "sk-CHANGE_ME"
    fallback_model: str = "gemini-3.1-flash-lite-preview"

    # ── Telegram notifications ────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── YouTube Data API ──────────────────────────────────────
    youtube_api_key: str = ""

    # ── Storage ───────────────────────────────────────────────
    storage_path: str = "./output"

    # ── Logging ───────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Derived helpers ───────────────────────────────────────
    @property
    def storage_dir(self) -> Path:
        """Return the resolved storage directory, creating it if needed."""
        path = Path(self.storage_path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def asyncpg_dsn(self) -> str:
        """Return the DSN in a format asyncpg accepts (no driver prefix)."""
        dsn = self.database_url
        if dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        return dsn

    def validate_production_config(self) -> ConfigValidationResult:
        """Validate production-only required configuration without exposing secrets."""
        if self.app_env.lower() != "production":
            return ConfigValidationResult(ok=True, errors={})

        errors: dict[str, str] = {}
        required_values = {
            "primary_api_key": self.primary_api_key,
            "youtube_api_key": self.youtube_api_key,
            "database_url": self.database_url,
            "redis_url": self.redis_url,
        }

        for field_name, value in required_values.items():
            if self._is_missing_or_placeholder(value):
                errors[field_name] = "must be set to a real value"

        return ConfigValidationResult(ok=not errors, errors=errors)

    @staticmethod
    def _is_missing_or_placeholder(value: str) -> bool:
        normalized = value.strip()
        if not normalized:
            return True
        unsafe_markers = ("CHANGE_ME", "your-", "xxx", "placeholder")
        return any(marker.lower() in normalized.lower() for marker in unsafe_markers)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
