from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class Room(SQLModel, table=True):
    """Комната для совместной работы. У каждого пользователя есть своя."""

    id: str = Field(primary_key=True, max_length=16)  # код из ссылки-приглашения
    owner_id: UUID = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
