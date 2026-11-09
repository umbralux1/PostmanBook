"""Комнаты: личная комната, приглашение, имя, WebSocket, общий зачёт заданий."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlmodel import Session, select
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.dependencies import SESSION_COOKIE
from app.main import app
from app.models import Room, User
from app.services.room_hub import RATE_BURST, RoomHub


def make_client(token: str) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.cookies.set(SESSION_COOKIE, token)
    return c


@pytest.fixture
def alice(engine: object) -> Iterator[TestClient]:
    with make_client("alice-session-token-1") as c:
        c.get("/")
        yield c


@pytest.fixture
def bob(engine: object) -> Iterator[TestClient]:
    with make_client("bob-session-token-0002") as c:
        c.get("/")
        yield c


def room_of(c: TestClient) -> dict[str, Any]:
    data: dict[str, Any] = c.get("/api/room").json()
    return data


def receive_type(
    ws: WebSocketTestSession,
    kind: str,
    where: Any = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Дождаться сообщения нужного типа (и, если задано, условия where(msg))."""
    for _ in range(limit):
        msg: dict[str, Any] = ws.receive_json()
        if msg["type"] == kind and (where is None or where(msg)):
            return msg
    raise AssertionError(f"не дождались {kind}")


def names(msg: dict[str, Any]) -> list[str]:
    return sorted(m["name"] for m in msg["members"])


def test_every_user_has_own_room(alice: TestClient, bob: TestClient) -> None:
    a, b = room_of(alice), room_of(bob)
    assert a["own"] is True and b["own"] is True
    assert a["code"] != b["code"]
    assert len(a["code"]) >= 11


def test_invite_join_and_leave(alice: TestClient, bob: TestClient, session: Session) -> None:
    code = room_of(alice)["code"]
    r = bob.get(f"/join/{code}", follow_redirects=False)
    assert r.status_code == 303
    info = room_of(bob)
    assert info["code"] == code and info["own"] is False
    bob.post("/rooms/leave", follow_redirects=False)
    assert room_of(bob)["own"] is True
    # Неизвестный код — остаёмся в своей комнате.
    own = room_of(bob)["code"]
    bob.get("/join/nope-nope-nope")
    assert room_of(bob)["code"] == own
    assert len(session.exec(select(Room)).all()) == 2


def test_set_name(alice: TestClient) -> None:
    r = alice.post("/api/me", json={"name": "   Аня   Петрова  "})
    assert r.json()["name"] == "Аня Петрова"
    assert room_of(alice)["me"]["name"] == "Аня Петрова"
    assert alice.post("/api/me", json={"name": "   "}).status_code == 422
    long = alice.post("/api/me", json={"name": "Я" * 90}).json()["name"]
    assert len(long) == 40


def test_ws_requires_membership(alice: TestClient, bob: TestClient) -> None:
    code = room_of(alice)["code"]
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        bob.websocket_connect(f"/ws/rooms/{code}") as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 4403


def test_ws_rejects_foreign_origin(alice: TestClient) -> None:
    code = room_of(alice)["code"]
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        alice.websocket_connect(
            f"/ws/rooms/{code}", headers={"origin": "https://evil.example"}
        ) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 4403


def test_ws_presence_patch_and_relay(alice: TestClient, bob: TestClient) -> None:
    alice.post("/api/me", json={"name": "Аня"})
    bob.post("/api/me", json={"name": "Борис"})
    code = room_of(alice)["code"]
    bob.get(f"/join/{code}")

    with alice.websocket_connect(f"/ws/rooms/{code}") as wa:
        welcome = wa.receive_json()
        assert welcome["type"] == "welcome" and welcome["state"] == {}
        wa.send_text(json.dumps({"type": "patch", "field": "url", "value": "http://x/api/echo"}))

        with bob.websocket_connect(f"/ws/rooms/{code}") as wb:
            wb_welcome = wb.receive_json()
            # Новый участник сразу получает общее состояние.
            assert wb_welcome["state"] == {"url": "http://x/api/echo"}
            assert sorted(m["name"] for m in wb_welcome["presence"]) == ["Аня", "Борис"]
            receive_type(wa, "presence", lambda m: len(m["members"]) == 2)

            wb.send_text(json.dumps({"type": "patch", "field": "body", "value": '{"a": 1}'}))
            patch = receive_type(wa, "patch")
            assert patch["field"] == "body" and patch["value"] == '{"a": 1}'
            assert patch["from"] == wb_welcome["conn"]

            wb.send_text(
                json.dumps(
                    {
                        "type": "cursor",
                        "page": "/chapters/ch01",
                        "path": [1, 2],
                        "rx": 0.5,
                        "ry": 0.25,
                        "secret": "не должно уйти",
                    }
                )
            )
            cur = receive_type(wa, "cursor")
            assert cur["rx"] == 0.5 and cur["path"] == [1, 2] and "secret" not in cur

            # Чужие поля и мусор игнорируются.
            wb.send_text(json.dumps({"type": "patch", "field": "__proto__", "value": 1}))
            wb.send_text("не json")
            wb.send_text(json.dumps({"type": "click", "page": "/", "path": [0], "rx": 0, "ry": 0}))
            assert receive_type(wa, "click")["path"] == [0]

        # Борис ушёл — Аня видит, что он пропал (его курсор фронт убирает по списку).
        receive_type(wa, "presence", lambda m: names(m) == ["Аня"])


def test_task_completion_is_credited_to_everyone_online(
    alice: TestClient, bob: TestClient, session: Session
) -> None:
    code = room_of(alice)["code"]
    bob.get(f"/join/{code}")
    with (
        alice.websocket_connect(f"/ws/rooms/{code}") as wa,
        bob.websocket_connect(f"/ws/rooms/{code}") as wb,
    ):
        wa.receive_json()
        wb.receive_json()
        r = alice.post("/api/tasks/ch01-task1/complete", json={"responses": []})
        assert r.json()["credited"] == 2
        assert receive_type(wb, "task_completed")["task_id"] == "ch01-task1"
    assert bob.get("/api/progress").json()["ch01"]["ch01-task1"] is True
    assert alice.get("/api/progress").json()["ch01"]["ch01-task1"] is True


def test_offline_members_are_not_credited(alice: TestClient, bob: TestClient) -> None:
    code = room_of(alice)["code"]
    bob.get(f"/join/{code}")  # Боб в комнате, но страницу не открыл
    r = alice.post("/api/tasks/ch01-task1/complete", json={"responses": []})
    assert r.json()["credited"] == 1
    assert bob.get("/api/progress").json()["ch01"]["ch01-task1"] is False


def test_rename_updates_presence(alice: TestClient) -> None:
    code = room_of(alice)["code"]
    with alice.websocket_connect(f"/ws/rooms/{code}") as wa:
        assert wa.receive_json()["presence"][0]["name"] == ""  # «Гость» подставляет фронт
        alice.post("/api/me", json={"name": "Аня"})
        receive_type(wa, "presence", lambda m: names(m) == ["Аня"])


def test_existing_user_without_room_gets_one(engine: object, session: Session) -> None:
    session.add(User(session_token="legacy-user-token-01"))
    session.commit()
    with make_client("legacy-user-token-01") as c:
        assert room_of(c)["own"] is True


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


async def test_hub_rate_limit_and_cleanup() -> None:
    from uuid import uuid4

    h = RoomHub()
    a, b = FakeSender(), FakeSender()
    ca = await h.join("r1", uuid4(), "A", "#000000", a)
    await h.join("r1", uuid4(), "B", "#111111", b)
    b.sent.clear()
    for i in range(RATE_BURST + 50):
        await h.handle("r1", ca, json.dumps({"type": "patch", "field": "body", "value": str(i)}))
    assert len(b.sent) <= RATE_BURST + 1, "флуд должен ограничиваться"
    await h.leave("r1", ca)
    assert h.online_user_ids("r1") and "r1" in h.rooms
    cb = next(iter(h.rooms["r1"].connections.values()))
    await h.leave("r1", cb)
    assert "r1" not in h.rooms, "пустая комната удаляется вместе с состоянием"
