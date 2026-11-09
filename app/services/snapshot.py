"""Нормализованный «снимок» HTTP-запроса — общий вход для валидатора."""

import json
from typing import Any, TypedDict

from starlette.requests import Request


class RequestSnapshot(TypedDict):
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body_raw: str
    json: Any
    json_valid: bool | None  # None — тела нет


# Заголовки, которые не показываем и не храним (могут содержать секреты/шум).
_HIDDEN_HEADERS = {"cookie", "authorization", "proxy-authorization"}


def parse_body(raw: str) -> tuple[Any, bool | None]:
    if not raw.strip():
        return None, None
    try:
        return json.loads(raw), True
    except ValueError:
        return None, False


def make_snapshot(
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body_raw: str = "",
) -> RequestSnapshot:
    parsed, valid = parse_body(body_raw)
    return RequestSnapshot(
        method=method.upper(),
        path=path,
        query=dict(query or {}),
        headers={k.lower(): v for k, v in (headers or {}).items()},
        body_raw=body_raw,
        json=parsed,
        json_valid=valid,
    )


def snapshot_from_request(request: Request, body: bytes) -> RequestSnapshot:
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        key = k.lower()
        if key in _HIDDEN_HEADERS:
            headers[key] = "***скрыто***"
        else:
            headers[key] = v
    return make_snapshot(
        method=request.method,
        path=request.url.path,
        query=dict(request.query_params),
        headers=headers,
        body_raw=body.decode("utf-8", errors="replace"),
    )
