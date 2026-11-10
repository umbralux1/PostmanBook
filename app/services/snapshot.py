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


# Заголовки, которые не показываем и не храним целиком (секреты/шум).
_HIDDEN_HEADERS = {"cookie", "proxy-authorization"}
# Секреты: в ответе echo — `***` (урок главы 2), в журнале ученика — частично
# (`Bearer tok_3f…9a`), чтобы было видно схему и что токен ушёл тот (глава 4).
_SECRET_HEADERS = {"authorization", "x-api-key"}
HIDDEN = "***"


def partial_secret(value: str) -> str:
    """Начало и конец секрета: `tok_3f…9a`. Короткий — целиком `***`."""
    v = value.strip()
    if len(v) < 12:
        return HIDDEN
    return f"{v[:6]}…{v[-2:]}"


def mask_authorization(value: str) -> str:
    """Схема видна, токен — частично; пароль Basic (base64 легко раскодировать) — нет."""
    scheme, sep, rest = value.strip().partition(" ")
    rest = rest.strip()
    if not sep or not rest:
        if scheme.lower() in ("bearer", "basic", ""):
            return scheme
        return partial_secret(scheme)  # токен без слова Bearer
    if scheme.lower() == "basic":
        return f"{scheme} {HIDDEN}"
    return f"{scheme} {partial_secret(rest)}"


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


def snapshot_from_request(
    request: Request, body: bytes, partial_secrets: bool = False
) -> RequestSnapshot:
    """partial_secrets=False — секреты `***` (echo); True — частично (журнал ученика)."""
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        key = k.lower()
        if key in _HIDDEN_HEADERS or (key in _SECRET_HEADERS and not partial_secrets):
            headers[key] = HIDDEN
        elif key == "authorization":
            headers[key] = mask_authorization(v)
        elif key in _SECRET_HEADERS:
            headers[key] = partial_secret(v)
        else:
            headers[key] = v
    return make_snapshot(
        method=request.method,
        path=request.url.path,
        query=dict(request.query_params),
        headers=headers,
        body_raw=body.decode("utf-8", errors="replace"),
    )
