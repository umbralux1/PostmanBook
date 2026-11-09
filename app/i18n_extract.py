"""Сбор строк для перевода: python -m app.i18n_extract [--missing en].

Ищет строки-ключи каталога:
* шаблоны: {{ _("...") }};
* JS и Alpine-выражения: t("...") / t('...'), tr("...") в checker.js;
* Python: N_("..."), translate("..."), третий аргумент ApiError(...).
"""

import json
import re
import sys
from pathlib import Path

from app.config import get_settings
from app.i18n import LOCALES_DIR

APP = Path(__file__).resolve().parent

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("*.html", re.compile(r"""\b_\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")),
    ("*.html", re.compile(r"""\bt\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")),
    ("*.js", re.compile(r"""\b(?:t|tr)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")),
    ("*.py", re.compile(r"""\b(?:N_|translate)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")),
    (
        "*.py",
        re.compile(r"""ApiError\(\s*\d+,\s*"[^"]*",\s*"((?:[^"\\]|\\.)*)"()""", re.S),
    ),
]


def extract() -> set[str]:
    keys: set[str] = {get_settings().app_name}
    for glob, pattern in _PATTERNS:
        for path in APP.rglob(glob):
            if "vendor" in path.parts or path.name == "i18n_extract.py":
                continue
            text = path.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                key = m.group(1) if m.group(1) is not None else m.group(2)
                if key:
                    keys.add(key.encode().decode("unicode_escape").encode("latin-1").decode())
    return keys


def missing(lang: str) -> list[str]:
    path = LOCALES_DIR / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(k for k in extract() if k not in data)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--missing"]:
        print(json.dumps(missing(sys.argv[2]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(sorted(extract()), ensure_ascii=False, indent=2))
