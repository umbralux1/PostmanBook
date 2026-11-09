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
