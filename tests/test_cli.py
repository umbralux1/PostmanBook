from sqlmodel import Session, select

from app.cli import reset_progress
from app.models import Attempt, User


def test_reset_progress_removes_attempts_keeps_users(session: Session) -> None:
    users = [User(session_token=f"tok-{i}") for i in range(2)]
    session.add_all(users)
    session.commit()
    for u in users:
        session.add(Attempt(user_id=u.id, task_id="ch01-task1", passed=True))
    session.commit()

    assert reset_progress(session) == 2
    assert session.exec(select(Attempt)).all() == []
    assert len(session.exec(select(User)).all()) == 2
