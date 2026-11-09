from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class ReceivedRequest(SQLModel, table=True):
    """Запрос, пришедший с заголовком X-Task-Code (фаза 2: реальный Postman)."""

    __tablename__ = "received_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_code: str = Field(index=True, max_length=64)
    method: str = Field(max_length=10)
    path: str
    query: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    headers: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    body: str = Field(default="", sa_column=Column(Text, nullable=False))
    received_at: datetime = Field(default_factory=utcnow, index=True)
    validated: bool = False
    validation_result: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
