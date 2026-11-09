import os
from collections.abc import AsyncIterator, Iterator

os.environ.setdefault("TRAINER_DATABASE_URL", "sqlite://")
os.environ.setdefault("TRAINER_RATE_LIMIT_ENABLED", "false")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel

from app.config import Settings, get_settings
from app.db import create_tables, make_engine, set_engine
from app.dependencies import SESSION_COOKIE, limiter
from app.main import app
from app.services.task_loader import sync_content

# По умолчанию — SQLite в памяти. Чтобы прогнать тесты на Postgres (как на Render):
#   TRAINER_TEST_DATABASE_URL=postgres://user@host:5432/db pytest
TEST_DB_URL = Settings(
    database_url=os.environ.get("TRAINER_TEST_DATABASE_URL", "sqlite://")
).database_url


@pytest.fixture
def engine() -> Iterator[object]:
    eng = make_engine(TEST_DB_URL)
    set_engine(eng)
    if not TEST_DB_URL.startswith("sqlite"):
        import app.models  # noqa: F401

        SQLModel.metadata.drop_all(eng)  # чистая база на каждый тест
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
