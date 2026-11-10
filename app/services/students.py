"""Личный код ученика (`User.student_code`) и заголовок `X-Student-Id`.

Код показывается ученику на сайте; в запросах из настоящего Postman он передаётся
заголовком `X-Student-Id`. По нему учебный API выдаёт ученику его собственные тикеты
и считает его лимит запросов. Неизвестный или отсутствующий код — общая «песочница».
"""

from fastapi import Request
from sqlmodel import Session, select

from app.models import User
from app.models.user import STUDENT_CODE_ALPHABET as ALPHABET
from app.models.user import STUDENT_CODE_LENGTH as CODE_LENGTH
from app.models.user import new_student_code

STUDENT_HEADER = "x-student-id"


def normalize_code(value: str | None) -> str | None:
    """Код из заголовка: без пробелов, в верхнем регистре; None — если формат не тот."""
    if not value:
        return None
    code = value.strip().upper()
    if len(code) != CODE_LENGTH or any(ch not in ALPHABET for ch in code):
        return None
    return code


def student_header(request: Request) -> str | None:
    """Код из `X-Student-Id` (только формат, без проверки в БД)."""
    return normalize_code(request.headers.get(STUDENT_HEADER))


def find_student(session: Session, request: Request) -> User | None:
    """Пользователь по `X-Student-Id` или None (нет заголовка / неизвестный код)."""
    code = student_header(request)
    if code is None:
        return None
    return session.exec(select(User).where(User.student_code == code)).first()


def unique_student_code(session: Session) -> str:
    """Новый код, которого ещё нет в базе."""
    while True:
        code = new_student_code()
        if session.exec(select(User.id).where(User.student_code == code)).first() is None:
            return code
