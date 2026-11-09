import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, hosting_storage_warning, sqlite_path
from app.db import make_engine


def test_default_is_sqlite_file() -> None:
    assert Settings().database_url.startswith("sqlite")


def test_non_sqlite_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(database_url="postgresql://u:p@h/db")


@pytest.mark.parametrize(
    ("url", "path"),
    [
        ("sqlite:///./trainer.db", Path("./trainer.db")),
        ("sqlite:////srv/data/trainer.db", Path("/srv/data/trainer.db")),
        ("sqlite://", None),
    ],
)
def test_sqlite_path(url: str, path: Path | None) -> None:
    assert sqlite_path(url) == path


def test_file_engine_creates_folder_and_uses_wal(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "data" / "trainer.db"
    engine = make_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert db.parent.is_dir()
    assert mode == "wal" and fk == 1
    engine.dispose()
    assert sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_render_warning_without_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(database_url="sqlite:////srv/data/trainer.db")
    monkeypatch.delenv("RENDER", raising=False)
    assert hosting_storage_warning(s) is None
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("TRAINER_PERSISTENT_DISK", raising=False)
    warning = hosting_storage_warning(s)
    assert warning and "/srv/data/trainer.db" in warning
    monkeypatch.setenv("TRAINER_PERSISTENT_DISK", "true")
    assert hosting_storage_warning(s) is None
