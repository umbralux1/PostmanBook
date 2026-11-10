"""Служебные эндпоинты заданий: засчитывание (фазы 1–2) и журнал ученика (фаза 2)."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.api.rooms import credit_room
from app.db import get_engine
from app.dependencies import RATE_LIMIT, RequiredUserDep, SessionDep, limiter
from app.errors import ApiError
from app.i18n import get_lang
from app.models import Attempt, ReceivedRequest, Task
from app.models.user import utcnow
from app.services import recorder
from app.services.room_hub import hub
from app.services.sse import broker

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
journal_router = APIRouter(prefix="/api/journal", tags=["tasks"])


def get_task_or_404(session: SessionDep, task_code: str) -> Task:
    task = session.get(Task, task_code)
    if task is None:
        raise ApiError(
            404, "task_not_found", "Задание {code} не найдено.", params={"code": task_code}
        )
    return task


def _journal_since() -> datetime:
    return utcnow() - timedelta(minutes=recorder.JOURNAL_MINUTES)


@journal_router.get("")
@limiter.limit(RATE_LIMIT)
def journal(request: Request, session: SessionDep, user: RequiredUserDep) -> dict[str, Any]:
    """Запросы ученика из настоящего Postman за последние 30 минут (старые → новые).

    Ученик определяется по cookie сайта, а не по коду в URL: чужой журнал не увидеть.
    """
    stmt = (
        select(ReceivedRequest)
        .where(ReceivedRequest.student_code == user.student_code)
        .where(col(ReceivedRequest.received_at) >= _journal_since())
        .order_by(col(ReceivedRequest.received_at).desc())
        .limit(recorder.JOURNAL_LIMIT)
    )
    rows = list(reversed(session.exec(stmt).all()))
    lang = get_lang(request)
    return {
        "student_code": user.student_code,
        "items": [recorder.journal_entry(session, r, lang) for r in rows],
    }


@journal_router.get("/stream")
@limiter.limit(RATE_LIMIT)
async def journal_stream(request: Request, user: RequiredUserDep) -> StreamingResponse:
    """SSE: событие `request` с записью журнала при каждом новом запросе ученика."""
    lang = get_lang(request)
    channel = recorder.topic(user.student_code)

    def load(event: dict[str, Any]) -> dict[str, Any] | None:
        with Session(get_engine()) as s:
            r = s.get(ReceivedRequest, UUID(str(event.get("id"))))
            return recorder.journal_entry(s, r, lang) if r is not None else None

    async def gen() -> Any:
        async for chunk in broker.subscribe(channel, transform=load):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class CompleteIn(BaseModel):
    """Ответ(ы) сервера, по которым фронт засчитал задание. Хранится для истории."""

    responses: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


@router.post("/{task_code}/complete")
@limiter.limit(RATE_LIMIT)
async def complete_task(
    request: Request,
    task_code: str,
    body: CompleteIn,
    session: SessionDep,
    user: RequiredUserDep,
) -> dict[str, Any]:
    """Фронт проверил ответ(ы) сервера (checker.js) и сообщает, что задание выполнено.

    Фаза 1: мини-Postman в комнате общий, поэтому задание засчитывается всем, кто
    сейчас онлайн в комнате пользователя. Фаза 2: у каждого свой Postman и свой
    журнал — засчитывается только себе.
    """
    task = get_task_or_404(session, task_code)
    if task.phase not in (1, 2):
        raise ApiError(400, "wrong_phase", "Это задание засчитывается не через мини-Postman.")
    shared = task.phase == 1
    credited = credit_room(session, user) if shared else {user.id}
    source = "emulator" if shared else "postman"
    for user_id in credited:
        session.add(
            Attempt(
                user_id=user_id,
                task_id=task.id,
                passed=True,
                request_payload={"source": source, "by": str(user.id)},
                response_payload={"responses": body.responses},
            )
        )
    session.commit()
    if shared and user.room_id:
        await hub.broadcast(user.room_id, {"type": "task_completed", "task_id": task.id})
    return {"task_id": task.id, "passed": True, "credited": len(credited)}
