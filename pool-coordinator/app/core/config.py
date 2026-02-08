from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/openmesh"
    admin_email: str = "admin@openmesh.local"
    admin_password: str = "change-me"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance to avoid re-reading environment variables."""

    return Settings()


settings = get_settings()
DATABASE_URL = settings.database_url
