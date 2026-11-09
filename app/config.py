"""Настройки приложения (читаются из переменных окружения и .env)."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRAINER_", extra="ignore")

    app_name: str = "HTTP-тренажёр"
    debug: bool = False
    # TRAINER_DATABASE_URL или стандартное DATABASE_URL (так его часто называют хостинги).
    database_url: str = Field(
        default="sqlite:///./trainer.db",
        validation_alias=AliasChoices("TRAINER_DATABASE_URL", "DATABASE_URL", "database_url"),
    )
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
    def _postgres_driver(cls, url: str) -> str:
        """Хостинги (Render, Heroku) выдают postgres://… или postgresql://… без драйвера.

        SQLAlchemy по умолчанию взял бы psycopg2, которого нет в зависимостях, —
        подставляем psycopg (v3).
        """
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url


class DatabaseNotConfiguredError(RuntimeError):
    pass


def check_database_for_hosting(settings: Settings) -> None:
    """На Render SQLite бесполезна: файловая система временная, данные теряются.

    Вместо непонятной ошибки sqlite3 сразу говорим, что нужно настроить.
    """
    if os.environ.get("RENDER") and settings.database_url.startswith("sqlite"):
        raise DatabaseNotConfiguredError(
            "База данных не настроена. На Render задайте переменную TRAINER_DATABASE_URL "
            "(или DATABASE_URL) = Internal Database URL вашей базы Postgres: "
            "Dashboard → сервис → Environment. Проще всего создать сервис через "
            "New → Blueprint: render.yaml создаст базу и переменную сам. "
            "SQLite на Render не подходит — данные теряются при каждом перезапуске."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
