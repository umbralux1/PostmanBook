from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class ReceivedRequest(SQLModel, table=True):
    """Запрос ученика из настоящего Postman (фаза 2) — вместе с ответом сервера.

    Пишется, когда в запросе есть `X-Student-Id` известного ученика
    (`services/recorder.py`). `task_code` пустой, если нет `X-Task-Code`.
    """

    __tablename__ = "received_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_code: str = Field(index=True, max_length=64)
    student_code: str | None = Field(default=None, index=True, max_length=6)
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
    # Ответ сервера: по нему фронт проверяет задание (static/js/checker.js).
    response_status: int | None = None
    response_headers: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
    response_body: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )
