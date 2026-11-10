"""Учебный API: GET /api/limited — эндпоинт с маленьким лимитом (тренировка 429)."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.errors import ApiError
from app.i18n import N_, get_lang, translate
from app.services import limited
from app.services.students import student_header

router = APIRouter(prefix="/api", tags=["training-api"])


def limit_key(request: Request) -> str:
    """Лимит на ученика (X-Student-Id), без него — на IP."""
    code = student_header(request)
    if code:
        return f"student:{code}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


@router.get("/limited")
def limited_endpoint(request: Request) -> JSONResponse:
    w = limited.window
    decision = w.hit(limit_key(request))
    headers = {
        "X-RateLimit-Limit": str(w.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        raise ApiError(
            429,
            "rate_limited",
            "Слишком много запросов: не больше {limit} за {window} с. Повторите через {retry} с — это число есть в заголовке ответа Retry-After.",  # noqa: E501
            {
                "limit": w.limit,
                "window_seconds": int(w.window),
                "retry_after": decision.retry_after,
            },
            headers={**headers, "Retry-After": str(decision.retry_after)},
            params={"limit": w.limit, "window": int(w.window), "retry": decision.retry_after},
        )
    payload: dict[str, Any] = {
        "ok": True,
        "message": translate(
            N_("Запрос принят. Осталось запросов в этом окне: {remaining}."),
            get_lang(request),
            remaining=decision.remaining,
        ),
        "limit": w.limit,
        "window_seconds": int(w.window),
        "remaining": decision.remaining,
    }
    return JSONResponse(payload, headers=headers)
