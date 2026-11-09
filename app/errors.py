"""Единый формат ошибок API: {"error": "code", "message": "...", "details": {...}}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.i18n import get_lang, translate

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        error: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """message — русский текст-ключ каталога; {name} подставляются из params."""
        super().__init__(message)
        self.params = params or {}
        self.status_code = status_code
        self.error = error
        self.message = message
        self.details = details or {}
        self.headers = headers


def translate_details(details: dict[str, Any], lang: str) -> dict[str, Any]:
    """Перевести строковые значения словаря details.invalid (описания ошибок полей)."""
    invalid = details.get("invalid")
    if isinstance(invalid, dict):
        details = {
            **details,
            "invalid": {
                k: translate(v, lang) if isinstance(v, str) else v for k, v in invalid.items()
            },
        }
    return details


def error_body(error: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": error, "message": message, "details": details or {}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        lang = get_lang(request)
        message = translate(exc.message, lang, **exc.params)
        details = translate_details(exc.details, lang)
        return JSONResponse(
            error_body(exc.error, message, details),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else code
        return JSONResponse(
            error_body(code, message),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body(
                "validation_error",
                translate("Некорректные параметры запроса", get_lang(request)),
                {"errors": errors},
            ),
            status_code=422,
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            error_body(
                "rate_limited",
                translate(
                    "Слишком много запросов. Подожди минуту и попробуй снова.", get_lang(request)
                ),
                {"limit": str(exc.detail)},
            ),
            status_code=429,
        )
