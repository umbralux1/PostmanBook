"""Генерация подсказок по результатам проверок.

Шаблоны подсказок берутся из секции `hints` задания (YAML). Подстановка
переменных `{{name}}` — простая замена по регулярному выражению, без
исполнения шаблонов.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.i18n import N_, SOURCE_LANG, translate

DEFAULT_HINTS: dict[str, str] = {
    "wrong_method": N_("Проверь метод запроса: нужен {{expected}}, а ушёл {{actual}}."),
    "wrong_path": N_("Проверь адрес: запрос должен идти на {{expected}}."),
    "missing_query": N_("В URL не хватает query-параметра: {{param}}."),
    "wrong_query": N_("У параметра {{param}} неверное значение: нужно {{expected}}."),
    "missing_content_type": N_("Добавь заголовок Content-Type: application/json."),
    "missing_header": N_("Не хватает заголовка: {{header}}."),
    "wrong_header": N_("У заголовка {{header}} неверное значение: нужно {{expected}}."),
    "invalid_json": N_("Тело — невалидный JSON. Проверь кавычки и запятые."),
    "missing_field": N_("В теле не хватает обязательного поля: {{field}}."),
    "invalid_body": N_("Тело не соответствует заданию: {{reason}}"),
    "body_should_be_invalid": N_("Здесь тело нужно отправить с ошибкой, как у пользователя."),
    "body_missing_text": N_("В теле должно встречаться: {{text}}."),
    "sequence_incomplete": N_("Осталось отправить: {{remaining}}."),
    "first_attempt_not_failed": N_("Сначала воспроизведи ошибку пользователя."),
    "second_attempt_not_fixed": N_("Теперь исправь тело и отправь снова."),
    "console_not_opened": N_("Открой Console и отправь запрос ещё раз."),
    "post_with_json_required": N_("Сначала отправь POST с валидным JSON из задания 3."),
    "wrong_status": N_("Ожидался статус {{expected}}, а в ответе {{actual}}."),
    "missing_response_field": N_("В ответе не найдено поле {{field}}."),
    "wrong_response_field": N_(
        "Поле {{field}} в ответе должно быть {{expected}}, а там {{actual}}."
    ),
    "unparseable_response": N_("Не получилось разобрать ответ. Скопируй тело ответа целиком."),
}

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render(template: str, params: Mapping[str, Any]) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        return str(params[key]) if key in params else m.group(0)

    return _VAR_RE.sub(_sub, template)


def build_hints(
    checks: Iterable[Mapping[str, Any]],
    task_hints: Mapping[str, str],
    lang: str = SOURCE_LANG,
) -> list[str]:
    """Собрать тексты подсказок для всех непройденных проверок (без повторов).

    Подсказки задания (`hints` из YAML) уже на нужном языке; встроенные переводятся.
    """
    result: list[str] = []
    for check in checks:
        if check.get("ok"):
            continue
        key = check.get("hint")
        if not key:
            continue
        params: dict[str, Any] = dict(check.get("hint_params") or {})
        params.setdefault("expected", check.get("expected"))
        params.setdefault("actual", check.get("actual"))
        default = DEFAULT_HINTS.get(key)
        template = task_hints.get(key) or (translate(default, lang) if default else None)
        if not template:
            continue
        text = render(template, params)
        if text not in result:
            result.append(text)
    return result
