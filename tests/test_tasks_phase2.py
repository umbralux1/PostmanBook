import asyncio
import json

from httpx import AsyncClient
from sqlmodel import Session, select

from app.models import Attempt, Chapter, ReceivedRequest, Task
from app.services.sse import Broker

BODY = {"ticket_id": "123", "message": "Не работает кнопка сохранения", "priority": "high"}


async def test_postman_request_with_task_code_is_stored(
    postman: AsyncClient, session: Session
) -> None:
    r = await postman.post("/api/echo", json=BODY, headers={"X-Task-Code": "ch01-task3"})
    assert r.status_code == 200
    assert r.json()["task_code"] == "ch01-task3"
    rows = session.exec(select(ReceivedRequest)).all()
    assert len(rows) == 1
    rr = rows[0]
    assert rr.task_code == "ch01-task3" and rr.method == "POST" and rr.path == "/api/echo"
    assert json.loads(rr.body) == BODY
    # Задание фазы 1 — сервер его не проверяет, только логирует.
    assert rr.validated is False
    assert session.exec(select(Attempt)).all() == []


async def test_phase2_task_is_validated_on_server(postman: AsyncClient, session: Session) -> None:
    session.add(Chapter(id="ch98", title="Фаза 2", order=98, phase=2, content_md="", meta={}))
    session.add(
        Task(
            id="ch98-task1",
            chapter_id="ch98",
            order=1,
            title="Postman",
            description_md="",
            phase=2,
            hints={},
            expected={"method": "GET", "path": "/api/echo", "query": {"a": "1"}},
        )
    )
    session.commit()
    await postman.get("/api/echo?a=1", headers={"X-Task-Code": "ch98-task1"})
    r = await postman.get("/api/tasks/ch98-task1/last")
    assert r.json()["validated"] is True
    assert r.json()["validation"]["passed"] is True


async def test_request_without_task_code_not_stored(postman: AsyncClient, session: Session) -> None:
    await postman.get("/api/echo")
    assert session.exec(select(ReceivedRequest)).all() == []


async def test_unknown_task_code_is_logged_but_not_validated(
    postman: AsyncClient, session: Session
) -> None:
    await postman.get("/api/echo", headers={"X-Task-Code": "nope-42"})
    rr = session.exec(select(ReceivedRequest)).one()
    assert rr.validated is False


async def test_last_endpoint(postman: AsyncClient) -> None:
    r = await postman.get("/api/tasks/ch01-task1/last")
    assert r.status_code == 404
    assert r.json()["error"] == "no_requests"
    await postman.get("/api/echo?source=postman", headers={"X-Task-Code": "ch01-task1"})
    await postman.get(
        "/api/echo?source=postman&user=student", headers={"X-Task-Code": "ch01-task1"}
    )
    r = await postman.get("/api/tasks/ch01-task1/last")
    assert r.status_code == 200
    assert r.json()["query"] == {"source": "postman", "user": "student"}


async def test_status_requests_also_logged(postman: AsyncClient, session: Session) -> None:
    for code in (200, 404, 500):
        await postman.get(f"/api/status/{code}", headers={"X-Task-Code": "ch01-task5"})
    assert len(session.exec(select(ReceivedRequest)).all()) == 3


async def test_complete_marks_progress(client: AsyncClient, session: Session) -> None:
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


async def test_complete_validation(client: AsyncClient) -> None:
    assert (await client.post("/api/tasks/nope/complete", json={})).status_code == 404
    r = await client.post("/api/tasks/ch01-task1/complete", json={"responses": [{}] * 21})
    assert r.status_code == 422


async def test_sse_broker_delivers_events() -> None:
    broker = Broker()
    gen = broker.subscribe("ch01-task1", heartbeat=1.0)
    assert await gen.__anext__() == ": connected\n\n"
    assert broker.subscriber_count("ch01-task1") == 1
    nxt = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert broker.publish("ch01-task1", {"method": "GET"}) == 1
    chunk = await asyncio.wait_for(nxt, 1)
    assert chunk.startswith("event: request\n")
    assert '"method": "GET"' in chunk
    await gen.aclose()
    assert broker.subscriber_count("ch01-task1") == 0
