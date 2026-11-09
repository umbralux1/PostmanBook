"""Учебный API: CRUD заявок /api/tickets."""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from sqlmodel import col, select

from app.api.echo import read_body
from app.dependencies import SessionDep
from app.errors import ApiError
from app.i18n import N_
from app.models import Ticket
from app.services import recorder
from app.services.snapshot import snapshot_from_request

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


async def parse_json_body(request: Request, session: SessionDep) -> Any:
    body = await read_body(request)
    snap = snapshot_from_request(request, body)
    ct = request.headers.get("content-type", "")
    if ct.split(";")[0].strip().lower() != "application/json":
        recorder.record(session, snap)
        raise ApiError(
            415,
            "unsupported_media_type",
            "Нужен заголовок Content-Type: application/json.",
            {"content_type": ct or None},
        )
    try:
        data = json.loads(body)
    except ValueError as exc:
        recorder.record(session, snap)
        raise ApiError(
            400, "invalid_json", "Тело запроса — невалидный JSON.", {"reason": str(exc)}
        ) from exc
    if not isinstance(data, dict):
        recorder.record(session, snap)
        raise ApiError(422, "validation_error", "Тело должно быть JSON-объектом {…}.")
    recorder.record(session, snap)
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


def get_ticket_or_404(session: SessionDep, ticket_id: int) -> Ticket:
    t = session.get(Ticket, ticket_id)
    if t is None:
        raise ApiError(404, "not_found", "Заявка {id} не найдена.", params={"id": ticket_id})
    return t


@router.get("")
def list_tickets(
    session: SessionDep,
    status: Literal["open", "in_progress", "closed"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    stmt = select(Ticket).order_by(col(Ticket.id))
    if status:
        stmt = stmt.where(Ticket.status == status)
    items = session.exec(stmt.limit(limit)).all()
    return {"items": [ticket_out(t) for t in items], "count": len(items)}


@router.post("", status_code=201)
async def create_ticket(request: Request, session: SessionDep) -> dict[str, Any]:
    data = await parse_json_body(request, session)
    clean = validate_fields(data, partial=False)
    t = Ticket(**clean)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, session: SessionDep) -> dict[str, Any]:
    return ticket_out(get_ticket_or_404(session, ticket_id))


@router.put("/{ticket_id}")
async def replace_ticket(ticket_id: int, request: Request, session: SessionDep) -> dict[str, Any]:
    t = get_ticket_or_404(session, ticket_id)
    clean = validate_fields(await parse_json_body(request, session), partial=False)
    t.title, t.priority = clean["title"], clean["priority"]
    t.status = clean.get("status", "open")
    t.description = clean.get("description", "")
    t.updated_at = datetime.now(UTC)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.patch("/{ticket_id}")
async def update_ticket(ticket_id: int, request: Request, session: SessionDep) -> dict[str, Any]:
    t = get_ticket_or_404(session, ticket_id)
    clean = validate_fields(await parse_json_body(request, session), partial=True)
    for key, value in clean.items():
        setattr(t, key, value)
    t.updated_at = datetime.now(UTC)
    session.add(t)
    session.commit()
    session.refresh(t)
    return ticket_out(t)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, session: SessionDep) -> Response:
    t = get_ticket_or_404(session, ticket_id)
    session.delete(t)
    session.commit()
    return Response(status_code=204)
