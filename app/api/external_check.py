"""Фаза 3: приём ответа внешнего API, вставленного пользователем."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.dependencies import RATE_LIMIT, RequiredUserDep, SessionDep, limiter
from app.errors import ApiError
from app.models import Attempt
from app.services.external_check import check_external_response

from .tasks import get_task_or_404

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class ExternalIn(BaseModel):
    raw: str = Field(min_length=1, max_length=64_000, description="Ответ, скопированный из Postman")


@router.post("/{task_code}/external")
@limiter.limit(RATE_LIMIT)
def submit_external(
    request: Request,
    task_code: str,
    body: ExternalIn,
    session: SessionDep,
    user: RequiredUserDep,
) -> dict[str, Any]:
    task = get_task_or_404(session, task_code)
    if task.phase != 3 or "response" not in task.expected:
        raise ApiError(
            400, "wrong_phase", "Это задание проверяется не через вставку ответа (не фаза 3)."
        )
    result = check_external_response(body.raw, task.expected, task.hints)
    session.add(
        Attempt(
            user_id=user.id,
            task_id=task.id,
            passed=bool(result["passed"]),
            request_payload={"external_raw": body.raw[:10_000]},
            response_payload={"validation": result},
        )
    )
    session.commit()
    return {"task_id": task.id, "validation": result}
