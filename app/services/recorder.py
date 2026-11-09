"""Запись запросов с заголовком X-Task-Code (фаза 2: свой Postman → учебный API).

В фазе 1 сервер ничего не проверяет: задание проверяется на фронте по ответу
сервера (static/js/checker.js). Здесь мы только логируем запрос и, для заданий
фазы 2, сравниваем его с эталоном запроса.
"""

import logging
from typing import Any

from sqlmodel import Session

from app.models import ReceivedRequest, Task
from app.services.snapshot import RequestSnapshot
from app.services.sse import broker
from app.services.validator import validate

log = logging.getLogger("trainer.recorder")

TASK_HEADER = "x-task-code"
MAX_TASK_CODE_LEN = 64


def task_code_of(snapshot: RequestSnapshot) -> str | None:
    code = snapshot["headers"].get(TASK_HEADER, "").strip()
    if not code or len(code) > MAX_TASK_CODE_LEN:
        return None
    return code


def record(session: Session, snapshot: RequestSnapshot) -> ReceivedRequest | None:
    """Сохранить запрос с X-Task-Code и разослать событие подписчикам SSE."""
    code = task_code_of(snapshot)
    if code is None:
        return None
    task = session.get(Task, code)

    validation: dict[str, Any] = {}
    if task is not None and task.phase == 2:
        validation = validate(snapshot, task.expected, task.hints)

    received = ReceivedRequest(
        task_code=code,
        method=snapshot["method"],
        path=snapshot["path"],
        query=snapshot["query"],
        headers=snapshot["headers"],
        body=snapshot["body_raw"],
        validated=bool(validation),
        validation_result=validation,
    )
    session.add(received)
    session.commit()

    broker.publish(
        code,
        {
            "id": str(received.id),
            "task_code": code,
            "method": received.method,
            "path": received.path,
            "received_at": received.received_at.isoformat(),
            "validation": validation or None,
        },
    )
    return received
