from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    """Анонимный пользователь, опознаётся по cookie session_token."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_token: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utcnow)
    # Совместная работа: имя и цвет курсора, текущая комната.
    name: str | None = Field(default=None, max_length=40)
    color: str = Field(default="#6366f1", max_length=7)
    room_id: str | None = Field(default=None, foreign_key="room.id", index=True, max_length=16)
