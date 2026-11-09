"""Подключение к БД и сессии."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def set_engine(engine: Engine) -> None:
    """Подменить движок (используется в тестах)."""
    global _engine
    _engine = engine


def create_tables(engine: Engine) -> None:
    import app.models  # noqa: F401  — регистрируем все модели

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


PROJECT_DIR = Path(__file__).resolve().parent.parent
INITIAL_REVISION = "6366cbaf6939"


def run_migrations(engine: Engine) -> None:
    """Довести схему БД до последней миграции Alembic.

    Базы, созданные раньше через create_all (без таблицы alembic_version),
    сначала помечаются первой миграцией, а затем обновляются.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config()  # без файла: не трогаем настройки логирования приложения
    cfg.set_main_option("script_location", str(PROJECT_DIR / "alembic"))
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "chapter" in tables:
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, "head")


def prepare_database(engine: Engine, url: str) -> None:
    """Dev-режим: in-memory → create_all, файл/сервер → миграции."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        create_tables(engine)
    else:
        run_migrations(engine)
