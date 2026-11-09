"""Прогресс текущего пользователя."""

from fastapi import APIRouter

from app.dependencies import SessionDep, UserDep
from app.services.progress import progress_map

router = APIRouter(prefix="/api", tags=["progress"])


@router.get("/progress")
def get_progress(session: SessionDep, user: UserDep) -> dict[str, dict[str, bool]]:
    """{chapter_id: {task_id: passed}}."""
    return progress_map(session, user)
