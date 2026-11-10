"""Общие зависимости FastAPI: сессия БД, текущий пользователь, rate limiter."""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import User

SESSION_COOKIE = "session_token"

_settings = get_settings()
limiter = Limiter(
    key_func=get_remote_address,
    enabled=_settings.rate_limit_enabled,
    headers_enabled=False,
)
RATE_LIMIT = _settings.rate_limit

SessionDep = Annotated[Session, Depends(get_session)]


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_of(request: Request) -> str | None:
    """Токен из cookie или выданный middleware в этом же запросе."""
    token = request.cookies.get(SESSION_COOKIE) or getattr(request.state, "session_token", None)
    if isinstance(token, str) and 8 <= len(token) <= 64:
        return token
    return None


def get_or_create_user(session: Session, token: str) -> User:
    user = session.exec(select(User).where(User.session_token == token)).first()
    if user is None:
        from app.services.students import unique_student_code

        user = User(session_token=token, student_code=unique_student_code(session))
        session.add(user)
        session.commit()
        session.refresh(user)
    if user.room_id is None:
        from app.services.rooms import ensure_room

        ensure_room(session, user)
    return user


def current_user(request: Request, session: SessionDep) -> User | None:
    """Пользователь сайта (по cookie). Для запросов из Postman — None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not 8 <= len(token) <= 64:
        return None
    return get_or_create_user(session, token)


def required_user(request: Request, session: SessionDep) -> User:
    token = session_token_of(request) or new_session_token()
    return get_or_create_user(session, token)


UserDep = Annotated[User | None, Depends(current_user)]
RequiredUserDep = Annotated[User, Depends(required_user)]
