"""Комнаты: личная комната у каждого, приглашение по ссылке, имя и цвет участника."""

import hashlib
import secrets

from sqlmodel import Session

from app.models import Room, User

# Хорошо различимые цвета курсоров.
PALETTE: tuple[str, ...] = (
    "#e11d48",
    "#2563eb",
    "#16a34a",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#4d7c0f",
    "#c2410c",
    "#4f46e5",
)
NAME_MAX = 40
ROOM_CODE_BYTES = 8  # 11 символов base64url — не подобрать перебором


def color_for(user: User) -> str:
    digest = hashlib.sha256(user.id.bytes).digest()
    return PALETTE[digest[0] % len(PALETTE)]


def new_room_code() -> str:
    return secrets.token_urlsafe(ROOM_CODE_BYTES)


def ensure_room(session: Session, user: User) -> Room:
    """Вернуть текущую комнату пользователя; при необходимости создать личную."""
    if user.room_id:
        room = session.get(Room, user.room_id)
        if room is not None:
            return room
    room = own_room(session, user)
    user.room_id = room.id
    user.color = color_for(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    return room


def own_room(session: Session, user: User) -> Room:
    from sqlmodel import select

    room = session.exec(select(Room).where(Room.owner_id == user.id)).first()
    if room is None:
        room = Room(id=new_room_code(), owner_id=user.id)
        session.add(room)
        session.commit()
        session.refresh(room)
    return room


def join_room(session: Session, user: User, code: str) -> Room | None:
    room = session.get(Room, code)
    if room is None:
        return None
    user.room_id = room.id
    session.add(user)
    session.commit()
    return room


def leave_room(session: Session, user: User) -> Room:
    """Вернуться в свою комнату."""
    room = own_room(session, user)
    user.room_id = room.id
    session.add(user)
    session.commit()
    return room


def clean_name(raw: str) -> str | None:
    name = " ".join(raw.split())[:NAME_MAX]
    return name or None
