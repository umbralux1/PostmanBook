"""Прогресс пользователя: какие задания пройдены."""

from sqlmodel import Session, select

from app.models import Attempt, Task, User


def passed_task_ids(session: Session, user: User | None) -> set[str]:
    if user is None:
        return set()
    stmt = select(Attempt.task_id).where(
        Attempt.user_id == user.id,
        Attempt.passed == True,  # noqa: E712
    )
    return set(session.exec(stmt).all())


def progress_map(session: Session, user: User | None) -> dict[str, dict[str, bool]]:
    """{chapter_id: {task_id: passed}}."""
    passed = passed_task_ids(session, user)
    result: dict[str, dict[str, bool]] = {}
    for task in session.exec(select(Task)).all():
        result.setdefault(task.chapter_id, {})[task.id] = task.id in passed
    return result


def quiz_task_id(chapter_id: str) -> str:
    return f"{chapter_id}-quiz"
