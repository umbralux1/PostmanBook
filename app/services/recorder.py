"""Журнал запросов ученика из настоящего Postman (фаза 2).

Запрос к учебному API с заголовком `X-Student-Id` известного ученика записывается
в `ReceivedRequest` вместе с ответом сервера (статус, заголовки, тело) — это делает
middleware в `app/main.py`. Новые записи рассылаются в личный SSE-канал ученика.

Задание проверяет фронт: тем же `static/js/checker.js`, что и в фазе 1, по ответам
на запросы с `X-Task-Code` = id задания. Здесь задание не засчитывается.
Для заданий фазы 2 с `expected.request` запрос дополнительно сравнивается с
эталоном (`validator.py`) — это только подсказки «что не так в запросе».

Запрос без `X-Student-Id` (или с неизвестным кодом) не записывается: неизвестно,
чей он. Запрос без `X-Task-Code` записывается с пустым `task_code` — в журнале
ученик видит подсказку, что заголовка не хватает.
"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request, Response
from sqlmodel import Session, select

from app.db import get_engine
from app.models import ReceivedRequest, Task, User
from app.services.localize import task_view
from app.services.snapshot import RequestSnapshot, make_snapshot, snapshot_from_request
from app.services.sse import broker
from app.services.students import student_header
from app.services.validator import validate

log = logging.getLogger("trainer.recorder")

TASK_HEADER = "x-task-code"
MAX_TASK_CODE_LEN = 64
# Служебные пути сайта: в журнал ученика не попадают. Остальное под /api/ — учебный
# API, включая опечатки в адресе (ученик увидит в журнале свой 404).
SERVICE_PREFIXES = ("/api/tasks", "/api/journal", "/api/room", "/api/me", "/api/progress")
MAX_STORED_BODY = 256 * 1024
# Журнал на странице: запросы ученика за последние N минут.
JOURNAL_MINUTES = 30
JOURNAL_LIMIT = 100


def task_code_of(snapshot: RequestSnapshot) -> str | None:
    code = snapshot["headers"].get(TASK_HEADER, "").strip()
    if not code or len(code) > MAX_TASK_CODE_LEN:
        return None
    return code


def topic(student_code: str) -> str:
    """Личный SSE-канал ученика."""
    return f"student:{student_code}"


def student_to_record(request: Request) -> str | None:
    """Код ученика, если запрос нужно записать в журнал (формат кода, без БД)."""
    path = request.url.path
    if not path.startswith("/api/") or path.startswith(SERVICE_PREFIXES):
        return None
    return student_header(request)


async def read_request_body(request: Request, limit: int) -> bytes:
    """Тело запроса для журнала. Слишком большое не читаем: его отклонит эндпоинт (413)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return b""
    return await request.body()


async def capture_response(response: Response) -> tuple[Response, bytes]:
    """Прочитать тело ответа и вернуть равноценный ответ (поток читается один раз)."""
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode())
    body = b"".join(chunks)
    copy = Response(content=body, status_code=response.status_code)
    copy.raw_headers = list(response.raw_headers)
    return copy, body


def store(
    student_code: str,
    snapshot: RequestSnapshot,
    status: int,
    headers: Mapping[str, str],
    body: bytes,
) -> ReceivedRequest | None:
    """Записать запрос с ответом и разослать событие в канал ученика."""
    with Session(get_engine()) as session:
        if session.exec(select(User.id).where(User.student_code == student_code)).first() is None:
            return None
        code = task_code_of(snapshot) or ""
        task = session.get(Task, code) if code else None
        validation: dict[str, Any] = {}
        request_expected = (task.expected or {}).get("request") if task else None
        if task is not None and task.phase == 2 and request_expected:
            validation = validate(snapshot, request_expected, task.hints)
        received = ReceivedRequest(
            task_code=code,
            student_code=student_code,
            method=snapshot["method"],
            path=snapshot["path"],
            query=snapshot["query"],
            headers=snapshot["headers"],
            body=snapshot["body_raw"][:MAX_STORED_BODY],
            validated=bool(validation),
            validation_result=validation,
            response_status=status,
            response_headers={k.lower(): v for k, v in headers.items()},
            response_body=body[:MAX_STORED_BODY].decode("utf-8", errors="replace"),
        )
        session.add(received)
        session.commit()
        session.refresh(received)
    broker.publish(topic(student_code), {"id": str(received.id)})
    return received


async def record_exchange(
    request: Request, request_body: bytes, response: Response, student_code: str
) -> Response:
    """Middleware: записать запрос и ответ ученика, вернуть ответ клиенту."""
    response, body = await capture_response(response)
    snap = snapshot_from_request(request, request_body)
    try:
        store(student_code, snap, response.status_code, response.headers, body)
    except Exception:  # журнал не должен ломать ответ учебного API
        log.exception("record_failed")
    return response


def _hints_for(r: ReceivedRequest, task: Task | None, lang: str) -> list[str]:
    """Подсказки validator.py на языке пользователя (проверка запроса, не ответа)."""
    if task is None or task.phase != 2:
        return []
    view = task_view(task, lang)
    expected = (view.expected or {}).get("request")
    if not expected:
        return []
    snap = make_snapshot(r.method, r.path, r.query, r.headers, r.body)
    result = validate(snap, expected, view.hints, lang=lang)
    hints: list[str] = result["hints"]
    return hints


def received_out(r: ReceivedRequest, task: Task | None, lang: str) -> dict[str, Any]:
    """Запись журнала для страницы главы фазы 2."""
    return {
        "id": str(r.id),
        "task_code": r.task_code,
        "known_task": task is not None,
        "method": r.method,
        "path": r.path,
        "query": r.query,
        "received_at": r.received_at.isoformat(),
        "response": {
            "status": r.response_status,
            "headers": r.response_headers,
            "body": r.response_body,
        },
        "hints": _hints_for(r, task, lang),
    }


def journal_entry(session: Session, r: ReceivedRequest, lang: str) -> dict[str, Any]:
    task = session.get(Task, r.task_code) if r.task_code else None
    return received_out(r, task, lang)
