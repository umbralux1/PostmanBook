"""Учебная авторизация (глава 4): учётка, токены, API-ключи.

У каждого ученика (`X-Student-Id`) своя учётка `agent` с паролем `support123`, свои
токены и ключи. Без кода ученика — общая «песочница» (owner = None), где пароль
поменять нельзя.

Токены — непрозрачные строки `tok_…`, ключи — `key_…` (JWT — в отдельной главе).
Смена пароля и сброс отзывают все токены и ключи ученика.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select, update

from app.models import AuthToken, User

USERNAME = "agent"
DEFAULT_PASSWORD = "support123"
ROLE = "agent"
ADMIN_ROLE = "admin"

DEFAULT_TTL = 900
MIN_TTL = 5
MAX_TTL = 3600

BEARER = "bearer"
API_KEY = "api_key"
PREFIXES = {BEARER: "tok_", API_KEY: "key_"}


def now() -> datetime:
    """Текущее время; в тестах подменяется, чтобы проверить просрочку без sleep."""
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def password_ok(user: User | None, password: str) -> bool:
    """Пароль учётки `agent` этого ученика (песочница — всегда по умолчанию)."""
    if user is None or user.auth_password_hash is None:
        return hmac.compare_digest(password, DEFAULT_PASSWORD)
    return hmac.compare_digest(hash_password(password), user.auth_password_hash)


def issue(session: Session, owner: str | None, kind: str, ttl: int | None = None) -> AuthToken:
    """Выдать токен (с ttl секунд) или ключ (без срока)."""
    issued = now()
    t = AuthToken(
        token=PREFIXES[kind] + secrets.token_hex(16),
        kind=kind,
        owner=owner,
        username=USERNAME,
        role=ROLE,
        created_at=issued,
        expires_at=issued + timedelta(seconds=ttl) if ttl is not None else None,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def find(session: Session, token: str) -> AuthToken | None:
    return session.exec(select(AuthToken).where(AuthToken.token == token)).first()


def is_expired(t: AuthToken) -> bool:
    return t.expires_at is not None and t.expires_at <= now()


def revoke_all(session: Session, owner: str) -> int:
    """Отозвать все действующие токены и ключи ученика; вернуть их число."""
    result = session.exec(
        update(AuthToken)
        .where(col(AuthToken.owner) == owner, col(AuthToken.revoked_at).is_(None))
        .values(revoked_at=now())
    )
    session.commit()
    return int(result.rowcount or 0)


def change_password(session: Session, user: User, new_password: str) -> int:
    user.auth_password_hash = hash_password(new_password)
    session.add(user)
    session.commit()
    return revoke_all(session, user.student_code)


def reset(session: Session, user: User) -> int:
    """Вернуть пароль по умолчанию и отозвать всё."""
    user.auth_password_hash = None
    session.add(user)
    session.commit()
    return revoke_all(session, user.student_code)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None
