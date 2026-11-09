"""Комнаты: WebSocket совместной работы, имя участника, приглашение и выход."""

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_engine
from app.dependencies import SESSION_COOKIE, RequiredUserDep, SessionDep
from app.errors import ApiError
from app.models import Room, User
from app.services import rooms
from app.services.room_hub import hub

router = APIRouter(tags=["rooms"])


def room_info(session: Session, user: User) -> dict[str, Any]:
    room = rooms.ensure_room(session, user)
    owner = session.get(User, room.owner_id)
    return {
        "code": room.id,
        "own": room.owner_id == user.id,
        "owner_name": owner.name if owner else None,
        "me": {"id": str(user.id), "name": user.name, "color": user.color},
        "online": hub.presence(room.id),
    }


@router.get("/api/room")
def get_room(session: SessionDep, user: RequiredUserDep) -> dict[str, Any]:
    return room_info(session, user)


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/api/me")
async def set_name(body: NameIn, session: SessionDep, user: RequiredUserDep) -> dict[str, Any]:
    name = rooms.clean_name(body.name)
    if name is None:
        raise ApiError(422, "validation_error", "Укажи имя.")
    user.name = name
    session.add(user)
    session.commit()
    await hub.rename(user.id, name)
    return {"name": name, "color": user.color}


@router.get("/join/{code}", include_in_schema=False)
def join(code: str, session: SessionDep, user: RequiredUserDep) -> RedirectResponse:
    """Ссылка-приглашение: войти в чужую комнату."""
    rooms.join_room(session, user, code)  # неизвестный код — просто остаёмся в своей
    return RedirectResponse("/", status_code=303)


@router.post("/rooms/leave", include_in_schema=False)
def leave(session: SessionDep, user: RequiredUserDep) -> RedirectResponse:
    rooms.leave_room(session, user)
    return RedirectResponse("/", status_code=303)


def _same_origin(ws: WebSocket) -> bool:
    """Браузер присылает Origin: принимаем подключения только со своего сайта."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True  # не браузер (тесты, утилиты) — cookie всё равно нужна
    return urlsplit(origin).netloc == ws.headers.get("host")


@router.websocket("/ws/rooms/{code}")
async def room_socket(ws: WebSocket, code: str) -> None:
    token = ws.cookies.get(SESSION_COOKIE)
    if not token or not _same_origin(ws):
        await ws.close(code=4403)
        return
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.session_token == token)).first()
        if user is None or user.room_id != code or session.get(Room, code) is None:
            await ws.close(code=4403)
            return
        user_id, name, color = user.id, user.name or "", user.color  # пустое → «Гость» на фронте

    await ws.accept()
    conn = await hub.join(code, user_id, name, color, ws)
    try:
        while True:
            raw = await ws.receive_text()
            await hub.handle(code, conn, raw)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(code, conn)


def credit_room(session: Session, user: User) -> set[Any]:
    """Кому засчитать задание: автору и всем, кто сейчас онлайн в его комнате."""
    ids = {user.id}
    if user.room_id:
        ids |= hub.online_user_ids(user.room_id)
    return ids


__all__ = ["credit_room", "room_info", "router"]
