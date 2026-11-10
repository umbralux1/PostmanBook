"""Прогресс текущего пользователя и кнопка Reset database."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlmodel import col, delete, select

from app.dependencies import RATE_LIMIT, RequiredUserDep, SessionDep, UserDep, limiter
from app.errors import ApiError
from app.models import Attempt, Chapter, Task
from app.services import auth_tokens
from app.services.progress import progress_map, quiz_task_id
from app.services.ticket_seed import reset_tickets

router = APIRouter(prefix="/api", tags=["progress"])


@router.get("/progress")
def get_progress(session: SessionDep, user: UserDep) -> dict[str, dict[str, bool]]:
    """{chapter_id: {task_id: passed}}."""
    return progress_map(session, user)


class ResetIn(BaseModel):
    chapter_id: str = Field(max_length=64)


@router.post("/progress/reset")
@limiter.limit(RATE_LIMIT)
def reset_chapter(
    request: Request, body: ResetIn, session: SessionDep, user: RequiredUserDep
) -> dict[str, Any]:
    """Кнопка «Reset database» в шапке страницы главы: начать главу заново — только себе.

    Удаляет попытки заданий и теста этой главы и снимает выбранное задание фазы 2,
    если оно из этой главы. Учебные данные API — только те, что перечислены в `reset`
    YAML главы: `tickets` — тикеты к учебному набору, `auth` — учётка /api/auth к
    паролю по умолчанию (токены отзываются).
    Прогресс других глав, имя, комната и личный код остаются. Служебный путь — в журнал
    не попадает. Чек-лист главы (localStorage) чистит страница.
    """
    chapter = session.get(Chapter, body.chapter_id)
    if chapter is None:
        raise ApiError(
            404, "chapter_not_found", "Глава {id} не найдена.", params={"id": body.chapter_id}
        )
    task_ids = list(session.exec(select(Task.id).where(Task.chapter_id == chapter.id)).all())
    attempts = session.exec(
        delete(Attempt).where(
            col(Attempt.user_id) == user.id,
            col(Attempt.task_id).in_([*task_ids, quiz_task_id(chapter.id)]),
        )
    )
    if user.phase2_task in task_ids:
        user.phase2_task = None
        session.add(user)
    session.commit()
    sandbox = chapter.meta.get("reset", [])
    if "tickets" in sandbox:
        reset_tickets(session, user)
    if "auth" in sandbox:
        auth_tokens.reset(session, user)
    return {"reset": True, "chapter_id": chapter.id, "attempts_deleted": attempts.rowcount}
