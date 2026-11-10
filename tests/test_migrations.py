"""Миграции на базе с данными: batch-режим SQLite пересоздаёт таблицы, на которые
ссылаются другие (user ← attempt), — это не должно падать на внешних ключах."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import PROJECT_DIR, make_engine


def test_upgrade_with_existing_users_and_attempts(tmp_path: Path, monkeypatch: object) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    monkeypatch.setenv("TRAINER_DATABASE_URL", url)  # type: ignore[attr-defined]
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(PROJECT_DIR / "alembic"))
        command.upgrade(cfg, "b04fa959aa58")  # до личных кодов учеников
        engine = make_engine(url)
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO user (id, session_token, created_at, color) "
                    "VALUES ('u1', 'tok-0001', '2026-01-01', '#000000')"
                )
            )
            c.execute(
                text(
                    "INSERT INTO attempt (id, user_id, task_id, passed, request_payload,"
                    " response_payload, created_at)"
                    " VALUES ('a1', 'u1', 'ch01-task1', 1, '{}', '{}', '2026-01-01')"
                )
            )
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            code = c.execute(text("SELECT student_code FROM user")).scalar_one()
            assert code and len(code) == 6
            assert c.execute(text("SELECT count(*) FROM attempt")).scalar_one() == 1
            assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        engine.dispose()
    finally:
        get_settings.cache_clear()
