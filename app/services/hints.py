"""Генерация подсказок по результатам проверок.

Шаблоны подсказок берутся из секции `hints` задания (YAML). Подстановка
переменных `{{name}}` — простая замена по регулярному выражению, без
исполнения шаблонов.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

DEFAULT_HINTS: dict[str, str] = {
    "wrong_method": "Проверь метод запроса: нужен {{expected}}, а ушёл {{actual}}.",
    "wrong_path": "Проверь адрес: запрос должен идти на {{expected}}.",
    "missing_query": "В URL не хватает query-параметра: {{param}}.",
    "wrong_query": "У параметра {{param}} неверное значение: нужно {{expected}}.",
    "missing_content_type": "Добавь заголовок Content-Type: application/json.",
    "missing_header": "Не хватает заголовка: {{header}}.",
    "wrong_header": "У заголовка {{header}} неверное значение: нужно {{expected}}.",
    "invalid_json": "Тело — невалидный JSON. Проверь кавычки и запятые.",
    "missing_field": "В теле не хватает обязательного поля: {{field}}.",
    "invalid_body": "Тело не соответствует заданию: {{reason}}",
    "body_should_be_invalid": "Здесь тело нужно отправить с ошибкой, как у пользователя.",
    "body_missing_text": "В теле должно встречаться: {{text}}.",
    "sequence_incomplete": "Осталось отправить: {{remaining}}.",
    "first_attempt_not_failed": "Сначала воспроизведи ошибку пользователя.",
    "second_attempt_not_fixed": "Теперь исправь тело и отправь снова.",
    "console_not_opened": "Открой вкладку Console и отправь запрос ещё раз.",
    "post_with_json_required": "Сначала отправь POST с валидным JSON из задания 3.",
    "wrong_status": "Ожидался статус {{expected}}, а в ответе {{actual}}.",
    "missing_response_field": "В ответе не найдено поле {{field}}.",
    "wrong_response_field": "Поле {{field}} в ответе должно быть {{expected}}, а там {{actual}}.",
    "unparseable_response": "Не получилось разобрать ответ. Скопируй тело ответа целиком.",
}

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render(template: str, params: Mapping[str, Any]) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        return str(params[key]) if key in params else m.group(0)

    return _VAR_RE.sub(_sub, template)


def build_hints(checks: Iterable[Mapping[str, Any]], task_hints: Mapping[str, str]) -> list[str]:
    """Собрать тексты подсказок для всех непройденных проверок (без повторов)."""
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
        template = task_hints.get(key) or DEFAULT_HINTS.get(key)
        if not template:
            continue
        text = render(template, params)
        if text not in result:
            result.append(text)
    return result
