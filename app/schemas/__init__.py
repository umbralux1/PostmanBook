"""Pydantic-схемы ответов API (используются для документации и тестов)."""

from typing import Any

from pydantic import BaseModel


class ErrorOut(BaseModel):
    error: str
    message: str
    details: dict[str, Any] = {}


class CheckOut(BaseModel):
    name: str
    ok: bool
    field: str | None = None
    expected: Any = None
    actual: Any = None


class ValidationOut(BaseModel):
    passed: bool
    checks: list[CheckOut]
    hints: list[str]


__all__ = ["CheckOut", "ErrorOut", "ValidationOut"]
