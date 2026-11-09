import pytest

from app.config import DatabaseNotConfiguredError, Settings, check_database_for_hosting


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


def test_database_url_accepts_standard_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRAINER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert Settings().database_url == "postgresql+psycopg://u:p@h/db"


def test_trainer_variable_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/other")
    monkeypatch.setenv("TRAINER_DATABASE_URL", "postgres://u:p@h/db")
    assert Settings().database_url.endswith("/db")


def test_sqlite_on_render_gives_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(DatabaseNotConfiguredError, match="TRAINER_DATABASE_URL"):
        check_database_for_hosting(Settings(database_url="sqlite:///./trainer.db"))
    check_database_for_hosting(Settings(database_url="postgres://u:p@h/db"))  # ок


def test_sqlite_locally_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    check_database_for_hosting(Settings(database_url="sqlite:///./trainer.db"))
