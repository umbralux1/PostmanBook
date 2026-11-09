"""Утилиты командной строки: `python -m app.cli check-content | sync-content | reset-progress`."""

import sys

from pydantic import ValidationError
from sqlmodel import Session, col, delete, func, select

from app.config import get_settings
from app.services.task_loader import (
    check_chapter_translation,
    check_tasks_translation,
    load_chapter_files,
    load_chapter_translations,
    load_task_files,
    load_task_translations,
)


def check_content() -> int:
    content_dir = get_settings().content_dir
    try:
        chapters = load_chapter_files(content_dir)
        task_files = load_task_files(content_dir)
        base_ch = {c.id: c for c in chapters}
        base_tasks = {t.chapter_id: t for t in task_files}
        langs: list[str] = []
        for lang, by_id in load_chapter_translations(content_dir).items():
            langs.append(lang)
            for cid, tr in by_id.items():
                if cid not in base_ch:
                    raise ValueError(f"Перевод {lang} для неизвестной главы {cid}")
                check_chapter_translation(base_ch[cid], tr, lang)
        for lang, by_ch in load_task_translations(content_dir).items():
            for cid, trt in by_ch.items():
                if cid not in base_tasks:
                    raise ValueError(f"Перевод {lang} заданий неизвестной главы {cid}")
                check_tasks_translation(base_tasks[cid], trt, lang)
    except (ValidationError, ValueError) as exc:
        print(f"Ошибка в контенте:\n{exc}", file=sys.stderr)
        return 1
    chapter_ids = {c.id for c in chapters}
    problems = [tf.chapter_id for tf in task_files if tf.chapter_id not in chapter_ids]
    if problems:
        print(f"Задания ссылаются на несуществующие главы: {problems}", file=sys.stderr)
        return 1
    n_tasks = sum(len(tf.tasks) for tf in task_files)
    extra = f", переводы: {', '.join(sorted(langs))}" if langs else ""
    print(f"OK: глав — {len(chapters)}, заданий — {n_tasks}{extra}")
    return 0


def sync_content_cmd() -> int:
    """Загрузить главы и задания из YAML в БД (без перезапуска приложения)."""
    if check_content() != 0:
        return 1
    from app.db import get_engine, prepare_database
    from app.services.task_loader import sync_content

    settings = get_settings()
    engine = get_engine()
    prepare_database(engine, settings.database_url)
    with Session(engine) as session:
        chapters, tasks = sync_content(session, settings.content_dir)
    print(f"Обновлено в БД: глав — {chapters}, заданий — {tasks}. Обнови страницу в браузере.")
    return 0


def reset_progress(session: Session) -> int:
    """Удалить попытки всех пользователей (задания и тесты глав). Вернуть, сколько удалено."""
    from app.models import Attempt

    count = session.exec(select(func.count(col(Attempt.id)))).one()
    session.exec(delete(Attempt))
    session.commit()
    return count


def reset_progress_cmd(argv: list[str]) -> int:
    """Сбросить прогресс всех пользователей. Без --yes спрашивает подтверждение."""
    from app.db import get_engine, prepare_database

    settings = get_settings()
    if "--yes" not in argv:
        answer = input(f"Удалить прогресс ВСЕХ пользователей в {settings.database_url}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return 1
    engine = get_engine()
    prepare_database(engine, settings.database_url)
    with Session(engine) as session:
        removed = reset_progress(session)
    print(f"Прогресс сброшен: удалено попыток — {removed}. Обнови страницу в браузере.")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["check-content"]:
        return check_content()
    if argv[1:2] == ["sync-content"]:
        return sync_content_cmd()
    if argv[1:2] == ["reset-progress"]:
        return reset_progress_cmd(argv[2:])
    print(
        "Использование: python -m app.cli check-content | sync-content | reset-progress [--yes]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
