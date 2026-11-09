"""Точка входа FastAPI."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session

from app import pages
from app.api import echo, external_check, progress, rooms, tasks, tickets
from app.config import BASE_DIR, check_database_for_hosting, get_settings
from app.db import get_engine, prepare_database
from app.dependencies import SESSION_COOKIE, limiter, new_session_token
from app.errors import install_error_handlers
from app.logging_setup import setup_logging
from app.services.task_loader import sync_content

log = logging.getLogger("trainer.http")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    check_database_for_hosting(settings)
    engine = get_engine()
    if settings.auto_create_tables:
        prepare_database(engine, settings.database_url)
    with Session(engine) as session:
        sync_content(session, settings.content_dir)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.debug)
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.limiter = limiter
    install_error_handlers(app)
    _ = RateLimitExceeded  # обработчик зарегистрирован в install_error_handlers

    allow_all = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else settings.cors_origins,
        # С "*" браузер не может слать cookie — это нормально для учебного API.
        allow_credentials=not allow_all,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=600,
    )

    @app.middleware("http")
    async def session_and_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        is_api = request.url.path.startswith("/api/")
        issued: str | None = None
        # Cookie выдаём только посетителям сайта, не запросам из Postman к API.
        if (
            not is_api
            and not request.url.path.startswith("/static/")
            and SESSION_COOKIE not in request.cookies
        ):
            issued = new_session_token()
            request.state.session_token = issued

        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        if issued:
            response.set_cookie(
                SESSION_COOKIE,
                issued,
                httponly=True,
                samesite="lax",
                secure=settings.cookie_secure,
                max_age=60 * 60 * 24 * 365,
            )
        if is_api:
            log.info(
                "api_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                    "client_ip": request.client.host if request.client else None,
                    "task_code": request.headers.get("x-task-code"),
                    "user_agent": request.headers.get("user-agent"),
                },
            )
        return response

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    for r in (
        echo.router,
        tickets.router,
        tasks.router,
        external_check.router,
        progress.router,
        rooms.router,
    ):
        app.include_router(r)
    app.include_router(pages.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
