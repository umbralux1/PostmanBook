"""Комнаты: личная комната, приглашение, имя, WebSocket, общий зачёт заданий."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from sqlmodel import Session, select
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect as ws_connect

from app.config import get_settings
from app.db import create_tables, make_engine, set_engine
from app.dependencies import SESSION_COOKIE
from app.main import app
from app.models import Room, User
from app.services.room_hub import RATE_BURST, RoomHub
from app.services.task_loader import sync_content

# ---------- Настоящий сервер для сценариев с несколькими участниками ----------
# TestClient запускает каждое WebSocket-подключение в своём потоке и event loop,
# поэтому рассылки между участниками в нём ненадёжны. В бою loop один (uvicorn),
# так что многопользовательские сценарии проверяем на живом uvicorn.


class LiveServer:
    def __init__(self, base: str) -> None:
        self.base = base
        self.ws_base = base.replace("http://", "ws://")


@pytest.fixture
def live(tmp_path: Path) -> Iterator[LiveServer]:
    engine = make_engine(f"sqlite:///{tmp_path / 'live.db'}")
    set_engine(engine)
    create_tables(engine)
    with Session(engine) as s:
        sync_content(s, get_settings().content_dir)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="websockets")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("live server did not start")
        time.sleep(0.02)
    try:
        yield LiveServer(f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        thread.join(5)
        engine.dispose()


class Member:
    """Участник: HTTP-клиент с cookie + WebSocket комнаты."""

    def __init__(self, live: LiveServer, token: str) -> None:
        self.live = live
        self.token = token
        self.http = httpx.Client(base_url=live.base, cookies={SESSION_COOKIE: token})
        self.http.get("/")

    def room(self) -> dict[str, Any]:
        data: dict[str, Any] = self.http.get("/api/room").json()
        return data

    def connect(self, code: str) -> Any:
        return ws_connect(
            f"{self.live.ws_base}/ws/rooms/{code}",
            additional_headers={"Cookie": f"{SESSION_COOKIE}={self.token}"},
            proxy=None,
            open_timeout=5,
        )


def recv(ws: Any, kind: str, where: Any = None, limit: int = 20) -> dict[str, Any]:
    """Дождаться сообщения нужного типа (таймаут — тест не зависает)."""
    for _ in range(limit):
        msg: dict[str, Any] = json.loads(ws.recv(timeout=5))
        if msg["type"] == kind and (where is None or where(msg)):
            return msg
    raise AssertionError(f"не дождались {kind}")


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


def test_ws_presence_patch_and_relay(live: LiveServer) -> None:
    alice, bob = Member(live, "alice-session-token-1"), Member(live, "bob-session-token-0002")
    alice.http.post("/api/me", json={"name": "Аня"})
    bob.http.post("/api/me", json={"name": "Борис"})
    code = alice.room()["code"]
    bob.http.get(f"/join/{code}")

    with alice.connect(code) as wa:
        welcome = recv(wa, "welcome")
        assert welcome["state"] == {}
        wa.send(json.dumps({"type": "patch", "field": "url", "value": "http://x/api/echo"}))
        time.sleep(0.1)  # патч дошёл до сервера раньше, чем подключится Борис

        with bob.connect(code) as wb:
            wb_welcome = recv(wb, "welcome")
            # Новый участник сразу получает общее состояние.
            assert wb_welcome["state"] == {"url": "http://x/api/echo"}
            assert sorted(m["name"] for m in wb_welcome["presence"]) == ["Аня", "Борис"]
            recv(wa, "presence", lambda m: len(m["members"]) == 2)

            wb.send(json.dumps({"type": "patch", "field": "body", "value": '{"a": 1}'}))
            patch = recv(wa, "patch")
            assert patch["field"] == "body" and patch["value"] == '{"a": 1}'
            assert patch["from"] == wb_welcome["conn"]

            wb.send(
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
            cur = recv(wa, "cursor")
            assert cur["rx"] == 0.5 and cur["path"] == [1, 2] and "secret" not in cur

            # Чужие поля и мусор игнорируются.
            wb.send(json.dumps({"type": "patch", "field": "__proto__", "value": 1}))
            wb.send("не json")
            wb.send(json.dumps({"type": "click", "page": "/", "path": [0], "rx": 0, "ry": 0}))
            assert recv(wa, "click")["path"] == [0]

        # Борис ушёл — Аня видит, что он пропал (его курсор фронт убирает по списку).
        recv(wa, "presence", lambda m: names(m) == ["Аня"])


def test_task_completion_is_credited_to_everyone_online(live: LiveServer) -> None:
    alice, bob = Member(live, "alice-session-token-1"), Member(live, "bob-session-token-0002")
    code = alice.room()["code"]
    bob.http.get(f"/join/{code}")
    with alice.connect(code) as wa, bob.connect(code) as wb:
        recv(wa, "welcome")
        recv(wb, "welcome")
        recv(wa, "presence", lambda m: len(m["members"]) == 2)
        r = alice.http.post("/api/tasks/ch01-task1/complete", json={"responses": []})
        assert r.json()["credited"] == 2
        assert recv(wb, "task_completed")["task_id"] == "ch01-task1"
    assert bob.http.get("/api/progress").json()["ch01"]["ch01-task1"] is True
    assert alice.http.get("/api/progress").json()["ch01"]["ch01-task1"] is True


def test_offline_members_are_not_credited(alice: TestClient, bob: TestClient) -> None:
    code = room_of(alice)["code"]
    bob.get(f"/join/{code}")  # Боб в комнате, но страницу не открыл
    r = alice.post("/api/tasks/ch01-task1/complete", json={"responses": []})
    assert r.json()["credited"] == 1
    assert bob.get("/api/progress").json()["ch01"]["ch01-task1"] is False


def test_rename_updates_presence(live: LiveServer) -> None:
    alice = Member(live, "alice-session-token-1")
    code = alice.room()["code"]
    with alice.connect(code) as wa:
        assert recv(wa, "welcome")["presence"][0]["name"] == ""  # «Гость» подставляет фронт
        alice.http.post("/api/me", json={"name": "Аня"})
        recv(wa, "presence", lambda m: names(m) == ["Аня"])


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
