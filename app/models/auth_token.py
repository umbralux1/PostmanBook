from datetime import datetime

from sqlmodel import Field, SQLModel


class AuthToken(SQLModel, table=True):
    """Токен или API-ключ учебной авторизации (глава 4, `/api/auth/*`)."""

    __tablename__ = "auth_token"

    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True, max_length=64)
    # bearer — токен из POST /api/auth/login; api_key — ключ из POST /api/auth/api-keys.
    kind: str = Field(max_length=10)
    # Код ученика (X-Student-Id); None — общая песочница.
    owner: str | None = Field(default=None, index=True, max_length=6)
    username: str = Field(max_length=40)
    role: str = Field(max_length=20)
    created_at: datetime
    expires_at: datetime | None = None  # у API-ключа срока нет
    revoked_at: datetime | None = None
