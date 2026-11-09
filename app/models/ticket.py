from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class Ticket(SQLModel, table=True):
    """Заявка в учебном API /api/tickets."""

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    priority: str = Field(max_length=10)
    status: str = Field(default="open", max_length=20, index=True)
    description: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
