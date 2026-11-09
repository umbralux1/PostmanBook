from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class Chapter(SQLModel, table=True):
    id: str = Field(primary_key=True, max_length=32)  # "ch01"
    title: str
    order: int = Field(index=True)
    phase: int = 1  # 1, 2 или 3
    content_md: str = Field(sa_column=Column(Text, nullable=False))
    # goal, after_completion, checklist, quiz, estimated_minutes
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # Переводы: {"en": {"title": ..., ...}}. Русский — в основных полях.
    translations: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
