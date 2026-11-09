import os
from collections.abc import AsyncIterator, Iterator

os.environ.setdefault("TRAINER_DATABASE_URL", "sqlite://")
os.environ.setdefault("TRAINER_RATE_LIMIT_ENABLED", "false")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session

from app.config import get_settings
from app.db import create_tables, make_engine, set_engine
from app.dependencies import SESSION_COOKIE, limiter
from app.main import app
from app.services.task_loader import sync_content


@pytest.fixture
def engine() -> Iterator[object]:
    eng = make_engine("sqlite://")  # SQLite в памяти, общий для всех соединений
    set_engine(eng)
    create_tables(eng)
    with Session(eng) as s:
        sync_content(s, get_settings().content_dir)
    limiter.enabled = False
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: object) -> Iterator[Session]:
    with Session(engine) as s:  # type: ignore[arg-type]
        yield s


@pytest.fixture
async def client(engine: object) -> AsyncIterator[AsyncClient]:
    """Клиент «как браузер»: с cookie сессии."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={SESSION_COOKIE: "test-session-token-0001"},
    ) as c:
        yield c


@pytest.fixture
async def postman(engine: object) -> AsyncIterator[AsyncClient]:
    """Клиент «как Postman»: без cookie."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
