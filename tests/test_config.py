import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./trainer.db", "sqlite:///./trainer.db"),
    ],
)
def test_database_url_gets_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
