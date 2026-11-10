"""Фаза 2: журнал запросов ученика из настоящего Postman, SSE, засчитывание, страница."""

import asyncio
import json
import threading
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import Session, select

from app.dependencies import SESSION_COOKIE
from app.models import Attempt, Chapter, ReceivedRequest, Task
from app.services.sse import Broker
from tests.test_rooms import LiveServer, live  # noqa: F401  — фикстура живого сервера

BODY = {"title": "Cannot log in", "priority": "high"}


async def student_code(client: AsyncClient) -> str:
    code: str = (await client.get("/api/room")).json()["me"]["student_code"]
    return code


def headers(code: str | None = None, task: str | None = None) -> dict[str, str]:
    h = {}
    if code:
        h["X-Student-Id"] = code
    if task:
        h["X-Task-Code"] = task
    return h


def add_phase2_task(session: Session, request: dict[str, Any] | None = None) -> None:
    session.add(Chapter(id="ch98", title="Фаза 2", order=98, phase=2, content_md="", meta={}))
    expected: dict[str, Any] = {"response": [{"path": "status", "equals": 200}]}
    if request:
        expected["request"] = request
    session.add(
        Task(
            id="ch98-task1",
            chapter_id="ch98",
            order=1,
            title="Postman",
            description_md="",
            phase=2,
            hints={},
            expected=expected,
            translations={},
        )
    )
    session.commit()


async def test_request_with_both_headers_is_stored_with_response(
    client: AsyncClient, postman: AsyncClient, session: Session
) -> None:
    code = await student_code(client)
    r = await postman.post("/api/tickets", json=BODY, headers=headers(code, "ch03-task3"))
    assert r.status_code == 201  # тело дошло до эндпоинта, хотя middleware его прочитал
    rr = session.exec(select(ReceivedRequest)).one()
    assert rr.student_code == code and rr.task_code == "ch03-task3"
    assert rr.method == "POST" and rr.path == "/api/tickets"
    assert json.loads(rr.body) == BODY
    assert rr.response_status == 201
    assert rr.response_headers["x-request-id"] == r.headers["x-request-id"]
    assert json.loads(rr.response_body)["id"] == r.json()["id"]
    # Сервер задание не засчитывает — это делает фронт по журналу.
    assert session.exec(select(Attempt)).all() == []


async def test_error_responses_are_stored_too(
    client: AsyncClient, postman: AsyncClient, session: Session
) -> None:
    code = await student_code(client)
    for _ in range(4):
        r = await postman.get("/api/limited", headers=headers(code, "ch03-task8"))
    assert r.status_code == 429
    last = session.exec(select(ReceivedRequest).where(ReceivedRequest.response_status == 429)).one()
    assert int(last.response_headers["retry-after"]) >= 1
    assert json.loads(last.response_body)["error"] == "rate_limited"


@pytest.mark.parametrize(
    "hdrs",
    [
        {"X-Task-Code": "ch03-task1"},  # нет X-Student-Id — неизвестно, чей запрос
        {"X-Student-Id": "ZZZZZZ", "X-Task-Code": "ch03-task1"},  # неизвестный код
        {"X-Student-Id": "bad", "X-Task-Code": "ch03-task1"},  # не тот формат
        {},
    ],
)
async def test_requests_without_known_student_are_not_stored(
    client: AsyncClient, postman: AsyncClient, session: Session, hdrs: dict[str, str]
) -> None:
    await student_code(client)
    r = await postman.get("/api/echo", headers=hdrs)
    assert r.status_code == 200  # учебный API отвечает как обычно
    assert session.exec(select(ReceivedRequest)).all() == []


async def test_request_without_task_code_is_logged_with_empty_code(
    client: AsyncClient, postman: AsyncClient
) -> None:
    code = await student_code(client)
    await postman.get("/api/tickets", headers=headers(code.lower()))  # регистр не важен
    items = (await client.get("/api/journal")).json()["items"]
    assert len(items) == 1
    assert items[0]["task_code"] == "" and items[0]["known_task"] is False
    assert items[0]["response"]["status"] == 200


async def test_service_endpoints_are_not_logged(
    client: AsyncClient, postman: AsyncClient, session: Session
) -> None:
    code = await student_code(client)
    await postman.get("/api/progress", headers=headers(code, "ch03-task1"))
    await postman.get("/healthz", headers=headers(code, "ch03-task1"))
    assert session.exec(select(ReceivedRequest)).all() == []


async def test_journal_is_personal(
    client: AsyncClient, postman: AsyncClient, engine: object
) -> None:
    mine = await student_code(client)
    async with AsyncClient(
        transport=client._transport,
        base_url="http://testserver",
        cookies={SESSION_COOKIE: "test-session-token-0002"},
    ) as other:
        theirs = await student_code(other)
        await postman.get("/api/echo?who=me", headers=headers(mine, "ch03-task1"))
        await postman.get("/api/echo?who=other", headers=headers(theirs, "ch03-task1"))
        got = (await client.get("/api/journal")).json()
        assert got["student_code"] == mine
        assert [e["query"] for e in got["items"]] == [{"who": "me"}]
        other_items = (await other.get("/api/journal")).json()["items"]
        assert [e["query"] for e in other_items] == [{"who": "other"}]


async def test_journal_entry_shape(
    client: AsyncClient, postman: AsyncClient, session: Session
) -> None:
    add_phase2_task(session)
    code = await student_code(client)
    await postman.get("/api/status/409", headers=headers(code, "ch98-task1"))
    await postman.get("/api/echo", headers=headers(code, "nope-1"))
    first, second = (await client.get("/api/journal")).json()["items"]  # старые → новые
    assert first["task_code"] == "ch98-task1" and first["known_task"] is True
    assert first["method"] == "GET" and first["path"] == "/api/status/409"
    assert first["response"]["status"] == 409
    assert json.loads(first["response"]["body"]) == {"status": 409}
    assert second["known_task"] is False and second["task_code"] == "nope-1"


async def test_validator_hints_in_user_language(
    client: AsyncClient, postman: AsyncClient, session: Session
) -> None:
    add_phase2_task(session, request={"method": "POST", "path": "/api/echo"})
    code = await student_code(client)
    await postman.get("/api/echo", headers=headers(code, "ch98-task1"))
    rr = session.exec(select(ReceivedRequest)).one()
    assert rr.validated is True and rr.validation_result["passed"] is False

    client.cookies.set("lang", "ru")
    ru = (await client.get("/api/journal")).json()["items"][0]["hints"]
    assert ru == ["Проверь метод запроса: нужен POST, а ушёл GET."]
    client.cookies.set("lang", "en")
    en = (await client.get("/api/journal")).json()["items"][0]["hints"]
    assert en == ["Check the request method: POST is needed, but GET was sent."]


async def test_journal_without_site_cookie_is_empty(
    client: AsyncClient, postman: AsyncClient
) -> None:
    code = await student_code(client)
    await postman.get("/api/echo", headers=headers(code, "ch03-task1"))
    # Код ученика в URL или заголовке не принимается — только cookie сайта.
    r = await postman.get("/api/journal", headers=headers(code))
    assert r.status_code == 200 and r.json()["items"] == []


async def test_complete_phase1_marks_progress(client: AsyncClient, session: Session) -> None:
    progress = (await client.get("/api/progress")).json()
    assert progress["ch01"]["ch01-task1"] is False
    r = await client.post(
        "/api/tasks/ch01-task1/complete",
        json={"responses": [{"status": 200, "headers": {}, "body": {}}]},
    )
    assert r.status_code == 200
    progress = (await client.get("/api/progress")).json()
    assert progress["ch01"]["ch01-task1"] is True
    assert progress["ch01"]["ch01-task2"] is False
    attempt = session.exec(select(Attempt)).one()
    assert attempt.passed is True and attempt.response_payload["responses"][0]["status"] == 200


async def test_complete_phase2_is_personal(client: AsyncClient, session: Session) -> None:
    add_phase2_task(session)
    r = await client.post("/api/tasks/ch98-task1/complete", json={"responses": []})
    assert r.status_code == 200 and r.json()["credited"] == 1
    attempt = session.exec(select(Attempt)).one()
    assert attempt.request_payload["source"] == "postman"
    assert (await client.get("/api/progress")).json()["ch98"]["ch98-task1"] is True


async def test_complete_validation(client: AsyncClient) -> None:
    assert (await client.post("/api/tasks/nope/complete", json={})).status_code == 404
    r = await client.post("/api/tasks/ch01-task1/complete", json={"responses": [{}] * 21})
    assert r.status_code == 422


async def test_sse_broker_delivers_events() -> None:
    broker = Broker()
    gen = broker.subscribe("student:AAAAAA", heartbeat=1.0)
    assert await gen.__anext__() == ": connected\n\n"
    assert broker.subscriber_count("student:AAAAAA") == 1
    nxt = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert broker.publish("student:AAAAAA", {"method": "GET"}) == 1
    chunk = await asyncio.wait_for(nxt, 1)
    assert chunk.startswith("event: request\n")
    assert '"method": "GET"' in chunk
    await gen.aclose()
    assert broker.subscriber_count("student:AAAAAA") == 0


async def test_sse_broker_transform_skips_none() -> None:
    broker = Broker()
    gen = broker.subscribe(
        "t", heartbeat=1.0, transform=lambda e: None if e["n"] == 1 else {"m": e["n"] * 10}
    )
    await gen.__anext__()
    nxt = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    broker.publish("t", {"n": 1})
    broker.publish("t", {"n": 2})
    chunk = await asyncio.wait_for(nxt, 1)
    assert '"m": 20' in chunk
    await gen.aclose()


def test_journal_stream_is_live_and_personal(live: LiveServer) -> None:  # noqa: F811
    """Живой uvicorn: запрос из «Postman» приходит в SSE ученика, чужой — нет."""
    me = httpx.Client(base_url=live.base, cookies={SESSION_COOKIE: "live-sse-token-0001"})
    other = httpx.Client(base_url=live.base, cookies={SESSION_COOKIE: "live-sse-token-0002"})
    pm = httpx.Client(base_url=live.base)
    my_code = me.get("/api/room").json()["me"]["student_code"]
    other_code = other.get("/api/room").json()["me"]["student_code"]
    events: list[dict[str, Any]] = []
    connected = threading.Event()

    def listen() -> None:
        with me.stream("GET", "/api/journal/stream", timeout=10) as r:
            for line in r.iter_lines():
                if line.startswith(": connected"):
                    connected.set()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    assert connected.wait(5)
    pm.get("/api/echo?who=other", headers=headers(other_code, "ch03-task1"))
    pm.get("/api/echo?who=me", headers=headers(my_code, "ch03-task1"))
    t.join(5)
    assert len(events) == 1
    assert events[0]["query"] == {"who": "me"}
    assert events[0]["task_code"] == "ch03-task1" and events[0]["response"]["status"] == 200
    for c in (me, other, pm):
        c.close()


async def test_phase2_chapter_page_has_no_mini_postman(client: AsyncClient) -> None:
    code = await student_code(client)
    html = (await client.get("/chapters/ch03")).text
    assert 'id="builder"' not in html and "js/builder.js" not in html
    assert 'id="postman-panel"' in html and "js/phase2.js" in html
    assert json.dumps(code) in html  # личный код для X-Student-Id
    phase1 = (await client.get("/chapters/ch01")).text
    assert 'id="builder"' in phase1 and "js/builder.js" in phase1
    assert "js/phase2.js" not in phase1


async def test_typo_in_api_path_is_logged(client: AsyncClient, postman: AsyncClient) -> None:
    """Опечатка в адресе учебного API тоже в журнале — ученик видит свой 404."""
    code = await student_code(client)
    await postman.get("/api/ech0", headers=headers(code, "ch03-task1"))
    items = (await client.get("/api/journal")).json()["items"]
    assert [(e["path"], e["response"]["status"]) for e in items] == [("/api/ech0", 404)]
