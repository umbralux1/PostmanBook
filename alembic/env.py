"""Alembic: миграции схемы. URL берётся из настроек приложения."""

from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

import app.models  # noqa: F401 — регистрирует таблицы в metadata
from app.config import get_settings
from app.db import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(get_settings().database_url)
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Batch-режим пересоздаёт таблицу (DROP + RENAME). При foreign_keys=ON SQLite
            # не даст удалить таблицу, на которую ссылаются строки других таблиц
            # (например, user ← attempt), — на время миграций проверку выключаем.
            # Вне транзакции: внутри неё PRAGMA foreign_keys не действует.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite не умеет ALTER COLUMN — Alembic пересоздаёт таблицу
        )
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"Миграция нарушила внешние ключи: {broken[:5]}")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
