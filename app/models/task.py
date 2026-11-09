from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True, max_length=64)  # "ch01-task3"
    chapter_id: str = Field(foreign_key="chapter.id", index=True)
    order: int
    title: str
    description_md: str = Field(sa_column=Column(Text, nullable=False))
    expected: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    hints: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    phase: int = 1
    # Переводы: {"en": {"title": ..., ...}}. Русский — в основных полях.
    translations: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
