"""Учебный API: /api/echo и /api/status/{code}."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.dependencies import RATE_LIMIT, limiter
from app.errors import ApiError, error_body
from app.i18n import get_lang, translate
from app.services import recorder
from app.services.snapshot import snapshot_from_request

router = APIRouter(prefix="/api", tags=["training-api"])

ALLOWED_STATUS_CODES: frozenset[int] = frozenset(
    {200, 201, 204, 301, 302, 400, 401, 403, 404, 409, 422, 429, 500, 502, 503}
)
_NO_BODY = {204, 301, 302}


async def read_body(request: Request) -> bytes:
    limit = get_settings().max_body_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(
            413, "payload_too_large", "Тело больше {limit} байт", params={"limit": limit}
        )
    body = await request.body()
    if len(body) > limit:
        raise ApiError(
            413, "payload_too_large", "Тело больше {limit} байт", params={"limit": limit}
        )
    return body


@router.api_route("/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@limiter.limit(RATE_LIMIT)
async def echo(request: Request) -> JSONResponse:
    """Вернуть всё, что пришло: метод, путь, параметры, заголовки, тело."""
    body = await read_body(request)
    snap = snapshot_from_request(request, body)
    content_type = snap["headers"].get("content-type", "")
    is_json_ct = "application/json" in content_type.lower()

    status = 200
    if is_json_ct and snap["json_valid"] is False:
        status = 400

    if status == 400:
        details: dict[str, Any] = {"body_raw": snap["body_raw"]}
        return JSONResponse(
            error_body(
                "invalid_json",
                translate(
                    "Тело запроса — невалидный JSON (Content-Type: application/json).",
                    get_lang(request),
                ),
                details,
            ),
            status_code=400,
        )

    payload: dict[str, Any] = {
        "method": snap["method"],
        "path": snap["path"],
        "args": snap["query"],
        "headers": snap["headers"],
        "json": snap["json"] if is_json_ct or snap["json_valid"] else None,
        "data": snap["body_raw"],
        "task_code": recorder.task_code_of(snap),
        "received_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    return JSONResponse(payload, status_code=status)


@router.api_route("/status/{code}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@limiter.limit(RATE_LIMIT)
async def status_code(code: str, request: Request) -> Response:
    """Вернуть запрошенный статус-код (только из белого списка)."""
    if not code.isdigit() or int(code) not in ALLOWED_STATUS_CODES:
        raise ApiError(
            400,
            "status_not_allowed",
            "Этот статус-код не поддерживается тренажёром.",
            {"allowed": sorted(ALLOWED_STATUS_CODES)},
        )
    value = int(code)
    await read_body(request)  # слишком большое тело → 413

    if value in _NO_BODY:
        headers = {"Location": "/api/echo"} if value in (301, 302) else None
        return Response(status_code=value, headers=headers)
    payload: dict[str, Any] = {"status": value}
    if value >= 500:
        # Номер запроса для эскалации — тот же, что в заголовке X-Request-ID.
        payload["request_id"] = getattr(request.state, "request_id", None)
    return JSONResponse(payload, status_code=value)
