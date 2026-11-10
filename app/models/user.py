import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


# Личный код ученика: 6 символов без похожих (0/O, 1/I/L).
STUDENT_CODE_LENGTH = 6
STUDENT_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_student_code() -> str:
    return "".join(secrets.choice(STUDENT_CODE_ALPHABET) for _ in range(STUDENT_CODE_LENGTH))


class User(SQLModel, table=True):
    """Анонимный пользователь, опознаётся по cookie session_token."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_token: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utcnow)
    # Совместная работа: имя и цвет курсора, текущая комната.
    name: str | None = Field(default=None, max_length=40)
    color: str = Field(default="#6366f1", max_length=7)
    room_id: str | None = Field(default=None, foreign_key="room.id", index=True, max_length=16)
    # Фаза 2: личный код для заголовка X-Student-Id (свои тикеты, лимит, журнал).
    student_code: str = Field(
        default_factory=new_student_code, index=True, unique=True, max_length=STUDENT_CODE_LENGTH
    )
    # Учебный набор тикетов уже выдан (повторно не создаётся, даже если всё удалить).
    tickets_seeded: bool = False
