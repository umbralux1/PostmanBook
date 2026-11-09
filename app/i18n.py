"""Интернационализация: язык пользователя и перевод строк интерфейса.

Исходный язык (SOURCE_LANG) — русский: строки в коде и шаблонах пишутся
по-русски и служат ключами каталога, а контент лежит в основных YAML-файлах.
Язык по умолчанию для пользователя (DEFAULT_LANG) — английский. Для английского берётся перевод из
`app/locales/en.json`. Если перевода нет, показывается исходная строка
(тест `tests/test_i18n.py` следит, чтобы такого не было).

Язык выбирается переключателем EN / RU (cookie `lang`), по умолчанию — английский.
Accept-Language браузера не учитывается: язык меняется только явным выбором.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from starlette.requests import Request

LANGUAGES: tuple[str, ...] = ("en", "ru")  # порядок — как в переключателе
SOURCE_LANG = "ru"  # язык исходных строк и основных файлов контента
DEFAULT_LANG = "en"  # язык для тех, кто ещё не выбрал
LANG_COOKIE = "lang"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_FORMAT_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@lru_cache
def catalog(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    if lang == SOURCE_LANG or not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def N_(text: str) -> str:  # имя маркера — как в gettext
    """Пометить строку для перевода там, где она переводится позже (ключ каталога)."""
    return text


def translate(text: str, lang: str, **params: Any) -> str:
    """Перевести строку и подставить {name}-параметры (простая замена, без format())."""
    result = catalog(lang).get(text, text) if lang != SOURCE_LANG else text
    if params:
        result = _FORMAT_RE.sub(
            lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), result
        )
    return result


def normalize_lang(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().lower()[:2]
    return code if code in LANGUAGES else None


def get_lang(request: Request) -> str:
    return normalize_lang(request.cookies.get(LANG_COOKIE)) or DEFAULT_LANG
