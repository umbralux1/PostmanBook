"""Комнаты в реальном времени: подключения, присутствие, общее состояние, ретрансляция.

Протокол (JSON по WebSocket /ws/rooms/{code}).

Клиент → сервер:
  {"type": "hello", "page": "/chapters/ch01"}           — где находится участник
  {"type": "cursor", "page", "path", "rx", "ry"}          — курсор (относительно элемента)
  {"type": "cursor_leave"}
  {"type": "click", "page", "path", "rx", "ry"}           — клик (рисуем «круги» у всех)
  {"type": "selection", "page", "sel": {...} | null}      — выделение текста / каретка
  {"type": "patch", "field": "body", "value": ...}        — изменение общего мини-Postman

Сервер → клиент:
  {"type": "welcome", "conn": id, "state": {...}, "presence": [...]}
  {"type": "presence", "members": [...]}
  ретранслированные сообщения с добавленным "from": conn-id

Сервер хранит последнее значение каждого поля общего состояния, чтобы новый
участник сразу увидел то же, что и остальные. Конфликтов не разрешаем:
выигрывает последнее изменение поля (для учебного тренажёра этого достаточно).

Состояние живёт в памяти процесса: нужен один воркер uvicorn (как и для SSE).
"""

import asyncio
import contextlib
import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

# Поля общего мини-Postman, которые можно менять через patch.
SHARED_FIELDS: frozenset[str] = frozenset(
    {
        "method",
        "url",
        "params",
        "headers",
        "bodyMode",
        "body",
        "tab",
        "respTab",
        "respView",
        "openedLog",
        "sending",
        "response",
        "log",
        "history",
        "consoleOpenedAt",
        "error",
        "taskId",
        "requestTabs",
        "activeTab",
    }
)
RELAY_TYPES: frozenset[str] = frozenset({"cursor", "cursor_leave", "click", "selection"})
MAX_MESSAGE_BYTES = 256 * 1024
RATE_PER_SECOND = 60  # средняя скорость
RATE_BURST = 120  # и запас для всплесков (быстрый набор текста)


class Sender(Protocol):
    async def send_text(self, data: str) -> None: ...


@dataclass
class Connection:
    id: str
    user_id: UUID
    name: str
    color: str
    sender: Sender
    page: str = "/"
    tokens: float = RATE_BURST
    last_refill: float = field(default_factory=time.monotonic)

    def allow(self) -> bool:
        """Token bucket: защищает комнату от флуда одного клиента."""
        now = time.monotonic()
        self.tokens = min(RATE_BURST, self.tokens + (now - self.last_refill) * RATE_PER_SECOND)
        self.last_refill = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True

    def public(self) -> dict[str, Any]:
        return {
            "conn": self.id,
            "user_id": str(self.user_id),
            "name": self.name,
            "color": self.color,
            "page": self.page,
        }


@dataclass
class RoomState:
    connections: dict[str, Connection] = field(default_factory=dict)
    shared: dict[str, Any] = field(default_factory=dict)


class RoomHub:
    def __init__(self) -> None:
        self.rooms: dict[str, RoomState] = {}
        self._ids = itertools.count(1)
        # Блокировка не нужна: всё работает в одном event loop, а изменения
        # словарей ниже не прерываются await-ами, то есть атомарны.

    # ---------- подключение ----------
    async def join(
        self, code: str, user_id: UUID, name: str, color: str, sender: Sender
    ) -> Connection:
        room = self.rooms.setdefault(code, RoomState())
        conn = Connection(
            id=f"c{next(self._ids)}", user_id=user_id, name=name, color=color, sender=sender
        )
        room.connections[conn.id] = conn
        await self._send(
            conn,
            {
                "type": "welcome",
                "conn": conn.id,
                "state": room.shared,
                "presence": self.presence(code),
            },
        )
        await self.broadcast_presence(code)
        return conn

    async def leave(self, code: str, conn: Connection) -> None:
        room = self.rooms.get(code)
        if room is None:
            return
        room.connections.pop(conn.id, None)
        if not room.connections:
            # Общее состояние живёт, пока в комнате кто-то есть.
            self.rooms.pop(code, None)
            return
        # Одно сообщение: новый список участников (фронт сам убирает курсоры ушедших).
        # shield — рассылка дойдёт, даже если задачу соединения отменяют (обрыв, остановка).
        await asyncio.shield(self.broadcast_presence(code))

    # ---------- сообщения от клиента ----------
    async def handle(self, code: str, conn: Connection, raw: str) -> None:
        if len(raw.encode()) > MAX_MESSAGE_BYTES or not conn.allow():
            return
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "hello":
            page = msg.get("page")
            if isinstance(page, str) and page.startswith("/") and len(page) <= 200:
                conn.page = page
                await self.broadcast_presence(code)
        elif kind == "patch":
            name = msg.get("field")
            if name not in SHARED_FIELDS:
                return
            room = self.rooms.get(code)
            if room is None:
                return
            room.shared[name] = msg.get("value")
            await self.broadcast(
                code,
                {"type": "patch", "field": name, "value": msg.get("value"), "from": conn.id},
                exclude=conn.id,
            )
        elif kind in RELAY_TYPES:
            out = {k: v for k, v in msg.items() if k in ("type", "page", "path", "rx", "ry", "sel")}
            out["from"] = conn.id
            await self.broadcast(code, out, exclude=conn.id)

    # ---------- рассылка ----------
    def presence(self, code: str) -> list[dict[str, Any]]:
        room = self.rooms.get(code)
        return [c.public() for c in room.connections.values()] if room else []

    def online_user_ids(self, code: str) -> set[UUID]:
        room = self.rooms.get(code)
        return {c.user_id for c in room.connections.values()} if room else set()

    async def rename(self, user_id: UUID, name: str) -> None:
        for code, room in list(self.rooms.items()):
            changed = False
            for c in room.connections.values():
                if c.user_id == user_id:
                    c.name = name
                    changed = True
            if changed:
                await self.broadcast_presence(code)

    async def broadcast_presence(self, code: str) -> None:
        await self.broadcast(code, {"type": "presence", "members": self.presence(code)})

    async def broadcast(self, code: str, msg: dict[str, Any], exclude: str | None = None) -> None:
        room = self.rooms.get(code)
        if room is None:
            return
        data = json.dumps(msg, ensure_ascii=False, default=str)
        targets = [c for c in room.connections.values() if c.id != exclude]
        await asyncio.gather(*(self._send_raw(c, data) for c in targets))

    async def _send(self, conn: Connection, msg: dict[str, Any]) -> None:
        await self._send_raw(conn, json.dumps(msg, ensure_ascii=False, default=str))

    @staticmethod
    async def _send_raw(conn: Connection, data: str) -> None:
        # Отвалившийся клиент не должен ронять рассылку остальным.
        with contextlib.suppress(Exception):
            await conn.sender.send_text(data)


hub = RoomHub()
