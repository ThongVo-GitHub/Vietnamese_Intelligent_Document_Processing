from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DocFlow VN API"
    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://docflow:docflow@localhost:5433/docflow"
    )
    upload_dir: Path = Path("data/uploads")
    max_upload_size_bytes: int = 10 * 1024 * 1024
    worker_poll_interval_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()