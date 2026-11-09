"""Глава и задание для показа: нужный язык + адрес сайта вместо {{BASE_URL}}.

В контенте адреса учебного API пишутся как `{{BASE_URL}}/api/echo`: сайт может
работать на localhost или на любом домене, а пользователь должен видеть полный
адрес — как в настоящем Postman.
"""

from types import SimpleNamespace
from typing import Any

from app.i18n import DEFAULT_LANG
from app.models import Chapter, Task

BASE_URL_TOKEN = "{{BASE_URL}}"


def fill_base_url(value: Any, base_url: str) -> Any:
    """Рекурсивно заменить {{BASE_URL}} во всех строках структуры."""
    if isinstance(value, str):
        return value.replace(BASE_URL_TOKEN, base_url)
    if isinstance(value, dict):
        return {k: fill_base_url(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_base_url(v, base_url) for v in value]
    return value


def chapter_view(ch: Chapter, lang: str, base_url: str = "") -> Any:
    tr: dict[str, Any] = ch.translations.get(lang, {}) if lang != DEFAULT_LANG else {}
    return SimpleNamespace(
        id=ch.id,
        order=ch.order,
        phase=ch.phase,
        title=tr.get("title", ch.title),
        content_md=fill_base_url(tr.get("content_md", ch.content_md), base_url),
        meta=fill_base_url(tr.get("meta", ch.meta), base_url),
        translated=bool(tr) or lang == DEFAULT_LANG,
    )


def task_view(task: Task, lang: str, base_url: str = "") -> Any:
    tr: dict[str, Any] = task.translations.get(lang, {}) if lang != DEFAULT_LANG else {}
    return SimpleNamespace(
        id=task.id,
        chapter_id=task.chapter_id,
        order=task.order,
        phase=task.phase,
        title=tr.get("title", task.title),
        description_md=fill_base_url(tr.get("description_md", task.description_md), base_url),
        expected=fill_base_url(tr.get("expected", task.expected), base_url),
        hints=tr.get("hints", task.hints),
    )
