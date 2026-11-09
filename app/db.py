"""Подключение к БД и сессии."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings, sqlite_path

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    """Движок SQLite: файл (папка создаётся сама) или база в памяти для тестов."""
    path = sqlite_path(url)
    if path is None:
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:
        cur = dbapi_conn.cursor()
        # WAL: чтение не блокирует запись — важно, когда учеников много одновременно.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


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
