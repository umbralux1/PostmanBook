"""Загрузка глав и заданий из YAML в БД.

Контент живёт в `app/content/chapters/*.yaml` и `app/content/tasks/*.yaml`.
Код только читает, валидирует (Pydantic) и синхронизирует его с таблицами.
"""

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session, select

from app.i18n import LANGUAGES, SOURCE_LANG
from app.models import Chapter, Task

log = logging.getLogger("trainer.content")


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: dict[str, str]
    answer: str
    explanation: str = ""

    @model_validator(mode="after")
    def _answer_in_options(self) -> "QuizQuestion":
        if self.answer not in self.options:
            raise ValueError(f"Ответ {self.answer!r} не входит в варианты вопроса {self.id}")
        return self


class ChapterFile(BaseModel):
    id: str
    title: str
    order: int
    phase: int = Field(ge=1, le=3)
    content_md: str
    estimated_minutes: int | None = None
    goal: str = ""
    after_completion: str = ""
    checklist: list[str] = []
    quiz: list[QuizQuestion] = []


class Assertion(BaseModel):
    """Одно ожидание к ответу сервера: {path, equals|contains|exists|in, hint}."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    path: str = Field(pattern=r"^(status|headers|body)(\.[^.]+)*$")
    equals: Any = None
    contains: str | None = None
    exists: bool | None = None
    in_: list[Any] | None = Field(default=None, alias="in")
    hint: str = ""

    @model_validator(mode="after")
    def _one_operator(self) -> "Assertion":
        given = [
            "equals" in self.model_fields_set,
            self.contains is not None,
            self.exists is not None,
            self.in_ is not None,
        ]
        if sum(given) != 1:
            raise ValueError(f"{self.path}: нужен ровно один из equals/contains/exists/in")
        return self


class ResponseCheck(BaseModel):
    """Фаза 1: каким должен быть ответ (или серия ответов) сервера."""

    model_config = ConfigDict(extra="forbid")

    response: list[Assertion] | None = None
    steps: list[list[Assertion]] | None = None
    ordered: bool = False
    require_console: bool = False
    console_hint: str = ""

    @model_validator(mode="after")
    def _response_or_steps(self) -> "ResponseCheck":
        if (self.response is None) == (self.steps is None):
            raise ValueError("укажите либо response, либо steps")
        return self


class TaskItem(BaseModel):
    id: str
    order: int
    title: str
    description_md: str
    expected: dict[str, Any]
    hints: dict[str, str] = {}
    phase: int = Field(default=1, ge=1, le=3)

    @field_validator("expected")
    @classmethod
    def _expected_not_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("expected не может быть пустым")
        return v

    @model_validator(mode="after")
    def _phase1_checks_response(self) -> "TaskItem":
        if self.phase == 1:
            ResponseCheck.model_validate(self.expected)
        return self


class TasksFile(BaseModel):
    chapter_id: str
    tasks: list[TaskItem]

    @model_validator(mode="after")
    def _unique_ids(self) -> "TasksFile":
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Повторяющиеся id заданий в главе {self.chapter_id}")
        return self


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _split_name(path: Path) -> tuple[str, str | None]:
    """ch01.yaml → ("ch01", None); ch01.en.yaml → ("ch01", "en")."""
    stem = path.name.removesuffix(".yaml")
    base, dot, lang = stem.rpartition(".")
    return (base, lang) if dot else (stem, None)


def _files(content_dir: Path, kind: str) -> tuple[list[Path], dict[str, list[Path]]]:
    """Основные файлы и переводы {lang: [файлы]}."""
    base: list[Path] = []
    translated: dict[str, list[Path]] = {}
    for p in sorted((content_dir / kind).glob("*.yaml")):
        _, lang = _split_name(p)
        if lang is None:
            base.append(p)
        else:
            if lang not in LANGUAGES or lang == SOURCE_LANG:
                raise ValueError(f"{p.name}: неизвестный язык перевода {lang!r}")
            translated.setdefault(lang, []).append(p)
    return base, translated


def load_chapter_files(content_dir: Path) -> list[ChapterFile]:
    base, _ = _files(content_dir, "chapters")
    return [ChapterFile.model_validate(_read_yaml(p)) for p in base]


def load_task_files(content_dir: Path) -> list[TasksFile]:
    base, _ = _files(content_dir, "tasks")
    return [TasksFile.model_validate(_read_yaml(p)) for p in base]


def load_chapter_translations(content_dir: Path) -> dict[str, dict[str, ChapterFile]]:
    """{lang: {chapter_id: ChapterFile}}."""
    _, translated = _files(content_dir, "chapters")
    return {
        lang: {c.id: c for c in (ChapterFile.model_validate(_read_yaml(p)) for p in paths)}
        for lang, paths in translated.items()
    }


def load_task_translations(content_dir: Path) -> dict[str, dict[str, TasksFile]]:
    """{lang: {chapter_id: TasksFile}}."""
    _, translated = _files(content_dir, "tasks")
    return {
        lang: {t.chapter_id: t for t in (TasksFile.model_validate(_read_yaml(p)) for p in paths)}
        for lang, paths in translated.items()
    }


_TEXT_KEYS = {"hint", "console_hint"}


def strip_texts(value: Any) -> Any:
    """Убрать из expected тексты подсказок — остаётся то, что проверяется."""
    if isinstance(value, dict):
        return {k: strip_texts(v) for k, v in value.items() if k not in _TEXT_KEYS}
    if isinstance(value, list):
        return [strip_texts(v) for v in value]
    return value


def check_chapter_translation(base: ChapterFile, tr: ChapterFile, lang: str) -> None:
    where = f"{base.id}.{lang}"
    if (tr.order, tr.phase) != (base.order, base.phase):
        raise ValueError(f"{where}: order/phase должны совпадать с оригиналом")
    if [(q.id, q.answer, sorted(q.options)) for q in tr.quiz] != [
        (q.id, q.answer, sorted(q.options)) for q in base.quiz
    ]:
        raise ValueError(f"{where}: вопросы теста (id, варианты, ответы) должны совпадать")
    if len(tr.checklist) != len(base.checklist):
        raise ValueError(f"{where}: в чек-листе должно быть столько же пунктов")


def check_tasks_translation(base: TasksFile, tr: TasksFile, lang: str) -> None:
    where = f"{base.chapter_id}.{lang}"
    if [t.id for t in tr.tasks] != [t.id for t in base.tasks]:
        raise ValueError(f"{where}: набор и порядок заданий должны совпадать с оригиналом")
    for b, t in zip(base.tasks, tr.tasks, strict=True):
        if (t.order, t.phase) != (b.order, b.phase):
            raise ValueError(f"{where}/{t.id}: order/phase должны совпадать")
        if strip_texts(t.expected) != strip_texts(b.expected):
            raise ValueError(
                f"{where}/{t.id}: expected должен совпадать с оригиналом (кроме текстов подсказок)"
            )
        if set(t.hints) != set(b.hints):
            raise ValueError(f"{where}/{t.id}: ключи hints должны совпадать")


def sync_content(session: Session, content_dir: Path) -> tuple[int, int]:
    """Загрузить/обновить контент в БД. Возвращает (кол-во глав, кол-во заданий)."""
    chapters = load_chapter_files(content_dir)
    chapter_ids = {c.id for c in chapters}
    ch_tr = load_chapter_translations(content_dir)
    for lang, by_id in ch_tr.items():
        for cid in by_id:
            if cid not in chapter_ids:
                raise ValueError(f"Перевод {lang} для неизвестной главы {cid}")

    for ch in chapters:
        meta = ch.model_dump(exclude={"id", "title", "order", "phase", "content_md"})
        translations: dict[str, Any] = {}
        for lang, by_id in ch_tr.items():
            if ch.id in by_id:
                tr = by_id[ch.id]
                check_chapter_translation(ch, tr, lang)
                translations[lang] = {
                    "title": tr.title,
                    "content_md": tr.content_md,
                    "meta": tr.model_dump(exclude={"id", "title", "order", "phase", "content_md"}),
                }
        row = session.get(Chapter, ch.id)
        if row is None:
            row = Chapter(
                id=ch.id,
                title=ch.title,
                order=ch.order,
                phase=ch.phase,
                content_md=ch.content_md,
                meta=meta,
                translations=translations,
            )
        else:
            row.title, row.order, row.phase = ch.title, ch.order, ch.phase
            row.content_md, row.meta, row.translations = ch.content_md, meta, translations
        session.add(row)
    session.flush()

    task_tr = load_task_translations(content_dir)
    n_tasks = 0
    for tf in load_task_files(content_dir):
        if tf.chapter_id not in chapter_ids:
            raise ValueError(f"Задания ссылаются на неизвестную главу {tf.chapter_id}")
        tr_by_lang: dict[str, dict[str, TaskItem]] = {}
        for lang, by_ch in task_tr.items():
            if tf.chapter_id in by_ch:
                check_tasks_translation(tf, by_ch[tf.chapter_id], lang)
                tr_by_lang[lang] = {t.id: t for t in by_ch[tf.chapter_id].tasks}
        for t in tf.tasks:
            translations = {
                lang: {
                    "title": items[t.id].title,
                    "description_md": items[t.id].description_md,
                    "expected": items[t.id].expected,
                    "hints": items[t.id].hints,
                }
                for lang, items in tr_by_lang.items()
            }
            task = session.get(Task, t.id)
            if task is None:
                task = Task(
                    id=t.id,
                    chapter_id=tf.chapter_id,
                    order=t.order,
                    title=t.title,
                    description_md=t.description_md,
                    expected=t.expected,
                    hints=t.hints,
                    phase=t.phase,
                    translations=translations,
                )
            else:
                task.chapter_id, task.order, task.title = tf.chapter_id, t.order, t.title
                task.description_md, task.expected = t.description_md, t.expected
                task.hints, task.phase, task.translations = t.hints, t.phase, translations
            session.add(task)
            n_tasks += 1
    session.commit()
    log.info("content synced", extra={"chapters": len(chapters), "tasks": n_tasks})
    return len(chapters), n_tasks


def list_chapters(session: Session) -> list[Chapter]:
    return list(session.exec(select(Chapter).order_by(Chapter.order)).all())  # type: ignore[arg-type]


def list_tasks(session: Session, chapter_id: str) -> list[Task]:
    stmt = select(Task).where(Task.chapter_id == chapter_id).order_by(Task.order)  # type: ignore[arg-type]
    return list(session.exec(stmt).all())
