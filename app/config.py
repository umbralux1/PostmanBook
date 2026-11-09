"""Настройки приложения (читаются из переменных окружения и .env)."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRAINER_", extra="ignore")

    app_name: str = "HTTP-тренажёр"
    debug: bool = False
    # База — SQLite-файл. В Docker: /srv/data/trainer.db (папку можно смонтировать как том/диск).
    database_url: str = "sqlite:///./trainer.db"
    # Готовить БД при старте: применить миграции Alembic (in-memory SQLite — create_all).
    # В Docker миграции запускаются отдельной командой перед стартом, здесь можно false.
    auto_create_tables: bool = True
    # Список разрешённых источников для CORS. "*" — разрешить всем (учебный API публичный).
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000", "*"]
    rate_limit: str = "60/minute"
    rate_limit_enabled: bool = True
    content_dir: Path = BASE_DIR / "content"
    # Публичный адрес сайта — показывается в подсказках для фазы 2.
    public_base_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    max_body_bytes: int = 64 * 1024

    @field_validator("database_url")
    @classmethod
    def _only_sqlite(cls, url: str) -> str:
        if not url.startswith("sqlite"):
            raise ValueError(
                "Проект работает на SQLite: TRAINER_DATABASE_URL должен начинаться с sqlite://, "
                "например sqlite:////srv/data/trainer.db"
            )
        return url


def sqlite_path(url: str) -> Path | None:
    """Путь к файлу базы или None для базы в памяти."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        return None
    return Path(url.split("///", 1)[1]) if "///" in url else None


def hosting_storage_warning(settings: Settings) -> str | None:
    """На Render без постоянного диска файл базы живёт до перезапуска сервиса."""
    if os.environ.get("RENDER") and not os.environ.get("TRAINER_PERSISTENT_DISK"):
        return (
            "SQLite на Render без постоянного диска: база удаляется при каждом деплое, "
            "перезапуске и засыпании сервиса. Подключите диск к папке с базой "
            f"({sqlite_path(settings.database_url)}) и задайте TRAINER_PERSISTENT_DISK=true."
        )
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
