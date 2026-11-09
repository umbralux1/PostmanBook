import json

import pytest
from httpx import AsyncClient
from sqlmodel import Session

from app.models import Chapter, Task
from app.services.external_check import check_external_response, parse_pasted_response

EXPECTED = {
    "response": {
        "status": 200,
        "required_keys": ["args", "headers"],
        "json_fields": {"args.source": "postman", "args.user": "student"},
    }
}
GOOD = {"args": {"source": "postman", "user": "student"}, "headers": {"host": "postman-echo.com"}}


def test_parse_plain_json() -> None:
    p = parse_pasted_response(json.dumps(GOOD))
    assert p["parsed"] and p["json"] == GOOD and p["status"] is None


def test_parse_with_status_line_and_headers() -> None:
    raw = "HTTP/1.1 200 OK\nContent-Type: application/json\n\n" + json.dumps(GOOD, indent=2)
    p = parse_pasted_response(raw)
    assert p["status"] == 200
    assert p["headers"]["content-type"] == "application/json"
    assert p["json"] == GOOD


def test_parse_garbage() -> None:
    assert parse_pasted_response("привет, это не ответ")["parsed"] is False


def test_check_passes() -> None:
    assert check_external_response(json.dumps(GOOD), EXPECTED, {})["passed"] is True


def test_check_wrong_field_and_status() -> None:
    bad = {"args": {"source": "browser"}, "headers": {}}
    raw = "404 Not Found\n" + json.dumps(bad)
    result = check_external_response(raw, EXPECTED, {})
    names = {c["name"]: c["ok"] for c in result["checks"]}
    assert names["status"] is False
    assert names["field:args.source"] is False
    assert names["field:args.user"] is False
    assert any("args.user" in h for h in result["hints"])


@pytest.fixture
def phase3_task(session: Session) -> Task:
    session.add(Chapter(id="ch99", title="Тест", order=99, phase=3, content_md="", meta={}))
    task = Task(
        id="ch99-task1",
        chapter_id="ch99",
        order=1,
        title="Внешний echo",
        description_md="",
        expected=EXPECTED,
        hints={},
        phase=3,
    )
    session.add(task)
    session.commit()
    return task


async def test_external_endpoint(client: AsyncClient, phase3_task: Task) -> None:
    r = await client.post(f"/api/tasks/{phase3_task.id}/external", json={"raw": json.dumps(GOOD)})
    assert r.status_code == 200
    assert r.json()["validation"]["passed"] is True
    progress = (await client.get("/api/progress")).json()
    assert progress["ch99"]["ch99-task1"] is True


async def test_external_endpoint_rejects_phase1_task(client: AsyncClient) -> None:
    r = await client.post("/api/tasks/ch01-task1/external", json={"raw": "{}"})
    assert r.status_code == 400
    assert r.json()["error"] == "wrong_phase"


async def test_external_endpoint_validates_input(client: AsyncClient) -> None:
    r = await client.post("/api/tasks/ch01-task1/external", json={"raw": ""})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"
    r = await client.post("/api/tasks/nope/external", json={"raw": "{}"})
    assert r.status_code == 404
