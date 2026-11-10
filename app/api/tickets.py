"""Учебный API: CRUD заявок /api/tickets."""

import json
import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.api.echo import read_body
from app.dependencies import SessionDep
from app.errors import ApiError
from app.i18n import N_
from app.models import Ticket
from app.services.students import find_student
from app.services.ticket_seed import SEED_TICKETS, ensure_seeded, reset_tickets

router = APIRouter(prefix="/api/tickets", tags=["training-api"])

PRIORITIES = ("low", "medium", "high")
STATUSES = ("open", "in_progress", "closed")
REQUIRED = ("title", "priority")


def ticket_out(t: Ticket) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "priority": t.priority,
        "status": t.status,
        "description": t.description,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


async def parse_json_body(request: Request) -> Any:
    body = await read_body(request)
    ct = request.headers.get("content-type", "")
    if ct.split(";")[0].strip().lower() != "application/json":
        raise ApiError(
            415,
            "unsupported_media_type",
            "Нужен заголовок Content-Type: application/json.",
            {"content_type": ct or None},
        )
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ApiError(
            400, "invalid_json", "Тело запроса — невалидный JSON.", {"reason": str(exc)}
        ) from exc
    if not isinstance(data, dict):
        raise ApiError(422, "validation_error", "Тело должно быть JSON-объектом {…}.")
    return data


def validate_fields(data: dict[str, Any], partial: bool) -> dict[str, Any]:
    missing = [] if partial else [f for f in REQUIRED if f not in data]
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}
    if "title" in data:
        title = data["title"]
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            errors["title"] = N_("строка длиной 1..200")
        else:
            clean["title"] = title.strip()
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            errors["priority"] = N_("одно из: low, medium, high")
        else:
            clean["priority"] = data["priority"]
    if "status" in data:
        if data["status"] not in STATUSES:
            errors["status"] = N_("одно из: open, in_progress, closed")
        else:
            clean["status"] = data["status"]
    if "description" in data:
        if not isinstance(data["description"], str) or len(data["description"]) > 2000:
            errors["description"] = N_("строка до 2000 символов")
        else:
            clean["description"] = data["description"]
    if missing or errors:
        message = (
            N_("Не хватает обязательных полей: {fields}")
            if missing
            else N_("Некоторые поля заполнены неверно.")
        )
        raise ApiError(
            422,
            "validation_error",
            message,
            {"missing": missing, "invalid": errors},
            params={"fields": ", ".join(missing)},
        )
    return clean


def ticket_owner(request: Request, session: SessionDep) -> str | None:
    """Код ученика из X-Student-Id; при первом обращении — выдать набор тикетов.

    Нет заголовка или код неизвестен — общая песочница (owner = None).
    """
    user = find_student(session, request)
    if user is None:
        return None
    ensure_seeded(session, user)
    return user.student_code


OwnerDep = Annotated[str | None, Depends(ticket_owner)]


def owned(stmt: SelectOfScalar[Any], owner: str | None) -> SelectOfScalar[Any]:
    return stmt.where(col(Ticket.owner).is_(None) if owner is None else Ticket.owner == owner)


def get_ticket_or_404(session: SessionDep, ticket_id: int, owner: str | None) -> Ticket:
    t = session.get(Ticket, ticket_id)
    if t is None or t.owner != owner:  # чужой тикет — как будто его нет
        raise ApiError(404, "not_found", "Заявка {id} не найдена.", params={"id": ticket_id})
    return t


def ensure_not_closed(t: Ticket, clean: dict[str, Any], reopening_allowed: bool) -> None:
    """Закрытый тикет менять нельзя; открыть можно только PATCH {"status": "open"}."""
    if t.status != "closed":
        return
    if reopening_allowed and clean.get("status") == "open":
        return
    raise ApiError(
        409,
        "ticket_closed",
        'Тикет {id} закрыт, его нельзя изменить. Сначала откройте его: PATCH с телом {"status": "open"}.',  # noqa: E501
        {"id": t.id, "status": t.status},
        params={"id": t.id},
    )


@router.get("")
def list_tickets(
    session: SessionDep,
    owner: OwnerDep,
    status: Literal["open", "in_progress", "closed"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    stmt = owned(select(Ticket), owner)
    if status:
        stmt = stmt.where(Ticket.status == status)
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    items = session.exec(
        stmt.order_by(col(Ticket.id)).offset((page - 1) * limit).limit(limit)
    ).all()
    return {
        "items": [ticket_out(t) for t in items],
        "page": page,
        "limit": limit,
        "total": total,
        "pages": math.ceil(total / limit),
        "count": len(items),
    }


@router.post("/reset")
def reset(session: SessionDep, request: Request) -> dict[str, Any]:
    """Вернуть тикеты ученика к учебному набору (нужен X-Student-Id)."""
    user = find_student(session, request)
    if user is None:
        raise ApiError(
            400,
            "student_required",
            "Нужен заголовок X-Student-Id с вашим личным кодом (он есть на сайте).",
        )
    reset_tickets(session, user)
    return {"reset": True, "total": len(SEED_TICKETS)}


@router.post("", status_code=201)
async def create_ticket(request: Request, session: SessionDep, owner: OwnerDep) -> dict[str, Any]:
    data = await parse_json_body(request)
    clean = validate_fields(data, partial=False)
    t = Ticket(**clean, owner=owner)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, session: SessionDep, owner: OwnerDep) -> dict[str, Any]:
    return ticket_out(get_ticket_or_404(session, ticket_id, owner))


@router.put("/{ticket_id}")
async def replace_ticket(
    ticket_id: int, request: Request, session: SessionDep, owner: OwnerDep
) -> dict[str, Any]:
    t = get_ticket_or_404(session, ticket_id, owner)
    clean = validate_fields(await parse_json_body(request), partial=False)
    ensure_not_closed(t, clean, reopening_allowed=False)
    t.title, t.priority = clean["title"], clean["priority"]
    t.status = clean.get("status", "open")
    t.description = clean.get("description", "")
    t.updated_at = datetime.now(UTC)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int, request: Request, session: SessionDep, owner: OwnerDep
) -> dict[str, Any]:
    t = get_ticket_or_404(session, ticket_id, owner)
    clean = validate_fields(await parse_json_body(request), partial=True)
    ensure_not_closed(t, clean, reopening_allowed=True)
    for key, value in clean.items():
        setattr(t, key, value)
    t.updated_at = datetime.now(UTC)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, session: SessionDep, owner: OwnerDep) -> Response:
    t = get_ticket_or_404(session, ticket_id, owner)
    session.delete(t)
    session.commit()
    return Response(status_code=204)
