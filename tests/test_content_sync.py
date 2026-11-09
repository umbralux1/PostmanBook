"""sync_content: то, что убрали из YAML, исчезает из БД."""

import shutil
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from app.config import get_settings
from app.models import Attempt, Chapter, Task, User
from app.services.task_loader import sync_content

CHAPTER = {
    "id": "ch99",
    "title": "Временная глава",
    "order": 99,
    "phase": 1,
    "content_md": "Текст",
}


def _task(n: int) -> dict[str, Any]:
    return {
        "id": f"ch99-task{n}",
        "order": n,
        "title": f"Задание {n}",
        "description_md": "Условие",
        "expected": {"response": [{"path": "status", "equals": 200}]},
    }


def _write(content: Path, tasks: list[dict[str, Any]] | None) -> None:
    ch, tf = content / "chapters/ch99.yaml", content / "tasks/ch99.yaml"
    if tasks is None:
        ch.unlink()
        tf.unlink()
        return
    ch.write_text(yaml.safe_dump(CHAPTER, allow_unicode=True), "utf-8")
    tf.write_text(
        yaml.safe_dump({"chapter_id": "ch99", "tasks": tasks}, allow_unicode=True), "utf-8"
    )


def _ids(session: Session, model: type[Chapter] | type[Task]) -> set[str]:
    return {row.id for row in session.exec(select(model)).all()}


def test_removed_task_and_chapter_leave_db(session: Session, tmp_path: Path) -> None:
    content = tmp_path / "content"
    shutil.copytree(get_settings().content_dir, content)
    user = User(session_token="test-sync")
    session.add(user)
    session.add(Attempt(user_id=user.id, task_id="ch99-task2", passed=True))
    session.commit()

    _write(content, [_task(1), _task(2)])
    sync_content(session, content)
    assert {"ch99-task1", "ch99-task2"} <= _ids(session, Task)

    _write(content, [_task(1)])
    sync_content(session, content)
    assert "ch99-task1" in _ids(session, Task)
    assert "ch99-task2" not in _ids(session, Task)

    _write(content, None)
    sync_content(session, content)
    assert "ch99" not in _ids(session, Chapter)
    assert not any(t.startswith("ch99-") for t in _ids(session, Task))
    assert "ch01" in _ids(session, Chapter)  # остальной контент на месте
    # История попыток не теряется.
    assert session.exec(select(Attempt).where(Attempt.task_id == "ch99-task2")).first()
