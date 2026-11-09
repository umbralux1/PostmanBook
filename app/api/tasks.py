"""Служебные эндпоинты заданий: фаза 1 (результат, действия), фаза 2 (last/stream)."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.rooms import credit_room
from app.dependencies import RATE_LIMIT, RequiredUserDep, SessionDep, limiter
from app.errors import ApiError
from app.models import Attempt, ReceivedRequest, Task
from app.services import recorder
from app.services.room_hub import hub
from app.services.sse import broker

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def get_task_or_404(session: SessionDep, task_code: str) -> Task:
    task = session.get(Task, task_code)
    if task is None:
        raise ApiError(
            404, "task_not_found", "Задание {code} не найдено.", params={"code": task_code}
        )
    return task


def received_out(r: ReceivedRequest) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "task_code": r.task_code,
        "method": r.method,
        "path": r.path,
        "query": r.query,
        "headers": r.headers,
        "body": r.body,
        "received_at": r.received_at.isoformat(),
        "validated": r.validated,
        "validation": r.validation_result or None,
    }


@router.get("/{task_code}/last")
@limiter.limit(RATE_LIMIT)
def last_request(request: Request, task_code: str, session: SessionDep) -> dict[str, Any]:
    """Последний запрос с этим X-Task-Code (для поллинга в фазе 2)."""
    stmt = (
        select(ReceivedRequest)
        .where(ReceivedRequest.task_code == task_code)
        .order_by(col(ReceivedRequest.received_at).desc())
        .limit(1)
    )
    r = session.exec(stmt).first()
    if r is None:
        raise ApiError(404, "no_requests", "Запросов с этим кодом пока не было.")
    return received_out(r)


@router.get("/{task_code}/stream")
@limiter.limit(RATE_LIMIT)
async def stream(request: Request, task_code: str) -> StreamingResponse:
    """SSE: событие `request` при каждом новом запросе с этим X-Task-Code."""
    if len(task_code) > recorder.MAX_TASK_CODE_LEN:
        raise ApiError(400, "bad_task_code", "Слишком длинный код задания.")

    async def gen() -> Any:
        async for chunk in broker.subscribe(task_code):
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
    """Фаза 1: фронт проверил ответ сервера и сообщает, что задание выполнено.

    Мини-Postman в комнате общий, поэтому задание засчитывается всем, кто
    сейчас онлайн в комнате пользователя.
    """
    task = get_task_or_404(session, task_code)
    if task.phase != 1:
        raise ApiError(400, "wrong_phase", "Это задание засчитывается не через мини-Postman.")
    credited = credit_room(session, user)
    for user_id in credited:
        session.add(
            Attempt(
                user_id=user_id,
                task_id=task.id,
                passed=True,
                request_payload={"source": "emulator", "by": str(user.id)},
                response_payload={"responses": body.responses},
            )
        )
    session.commit()
    if user.room_id:
        await hub.broadcast(user.room_id, {"type": "task_completed", "task_id": task.id})
    return {"task_id": task.id, "passed": True, "credited": len(credited)}
