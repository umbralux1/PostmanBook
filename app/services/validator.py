"""Сравнение фактического запроса с эталоном задания.

Каждая проверка независима и описывается словарём::

    {"name": "method", "field": "method", "ok": True,
     "expected": "POST", "actual": "POST", "hint": "wrong_method"}

`field` подсказывает UI, какую часть мини-Postman подсветить:
method | url | params | headers | body.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator

from app.services.hints import build_hints
from app.services.snapshot import RequestSnapshot

Check = dict[str, Any]
Result = dict[str, Any]

_PLACEHOLDER_RE = re.compile(r"\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\}")


def path_matches(pattern: str, actual: str) -> bool:
    """`/api/status/{{code}}` совпадает с `/api/status/404`."""
    regex = "[^/]+".join(
        re.escape(part) for part in _PLACEHOLDER_RE.split(pattern.rstrip("/") or "/")
    )
    return re.fullmatch(regex, actual.rstrip("/") or "/") is not None


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def check_method(actual: RequestSnapshot, expected: str) -> Check:
    exp = expected.upper()
    return {
        "name": "method",
        "field": "method",
        "ok": actual["method"] == exp,
        "expected": exp,
        "actual": actual["method"],
        "hint": "wrong_method",
    }


def check_path(actual: RequestSnapshot, expected: str) -> Check:
    return {
        "name": "path",
        "field": "url",
        "ok": path_matches(expected, actual["path"]),
        "expected": expected,
        "actual": actual["path"],
        "hint": "wrong_path",
    }


def check_query(actual: RequestSnapshot, expected: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []
    for key, value in expected.items():
        exp = str(value)
        got = actual["query"].get(key)
        checks.append(
            {
                "name": f"query:{key}",
                "field": "params",
                "ok": got == exp,
                "expected": exp,
                "actual": got,
                "hint": "missing_query" if got is None else "wrong_query",
                "hint_params": {"param": key},
            }
        )
    return checks


def check_headers(actual: RequestSnapshot, expected: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []
    for raw_key, value in expected.items():
        key = raw_key.lower()
        exp = str(value)
        got = actual["headers"].get(key)
        if key == "content-type":
            ok = got is not None and _media_type(got) == _media_type(exp)
            checks.append(
                {
                    "name": "content_type",
                    "field": "headers",
                    "ok": ok,
                    "expected": exp,
                    "actual": got,
                    "hint": "missing_content_type",
                }
            )
            continue
        checks.append(
            {
                "name": f"header:{key}",
                "field": "headers",
                "ok": got is not None and got.strip() == exp,
                "expected": exp,
                "actual": got,
                "hint": "missing_header" if got is None else "wrong_header",
                "hint_params": {"header": raw_key},
            }
        )
    return checks


def check_body(actual: RequestSnapshot, expected: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []
    valid = actual["json_valid"] is True
    checks.append(
        {
            "name": "body_valid_json",
            "field": "body",
            "ok": valid,
            "expected": True,
            "actual": actual["json_valid"],
            "hint": "invalid_json",
        }
    )
    schema = expected.get("json_schema")
    if not schema:
        return checks
    data = actual["json"] if valid else None

    required: Sequence[str] = schema.get("required", [])
    missing = [f for f in required if not isinstance(data, dict) or f not in data]
    checks.append(
        {
            "name": "body_required_fields",
            "field": "body",
            "ok": valid and not missing,
            "missing": missing,
            "hint": "missing_field" if missing else "invalid_json",
            "hint_params": {"field": ", ".join(missing)},
        }
    )
    if valid and not missing:
        errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
        reasons = [_describe_schema_error(e.path, e.message, e.validator) for e in errors]
        checks.append(
            {
                "name": "body_schema",
                "field": "body",
                "ok": not errors,
                "errors": reasons,
                "hint": "invalid_body",
                "hint_params": {"reason": "; ".join(reasons)},
            }
        )
    return checks


def _describe_schema_error(path: Any, message: str, validator: Any) -> str:
    where = ".".join(str(p) for p in path) or "тело"
    if validator == "enum":
        return f"поле «{where}» имеет недопустимое значение ({message})"
    if validator == "type":
        return f"поле «{where}» неверного типа ({message})"
    return f"{where}: {message}"


def run_checks(actual: RequestSnapshot, expected: Mapping[str, Any]) -> list[Check]:
    """Проверки «одного запроса»: method, path, query, headers, body и т.п."""
    checks: list[Check] = []
    if "method" in expected:
        checks.append(check_method(actual, str(expected["method"])))
    if "path" in expected:
        checks.append(check_path(actual, str(expected["path"])))
    if expected.get("query"):
        checks.extend(check_query(actual, expected["query"]))
    if expected.get("headers"):
        checks.extend(check_headers(actual, expected["headers"]))
    if "body_valid_json" in expected:
        want = bool(expected["body_valid_json"])
        got = actual["json_valid"] is True
        checks.append(
            {
                "name": "body_valid_json",
                "field": "body",
                "ok": got == want,
                "expected": want,
                "actual": got,
                "hint": "invalid_json" if want else "body_should_be_invalid",
            }
        )
    if "body_raw_contains" in expected:
        text = str(expected["body_raw_contains"])
        checks.append(
            {
                "name": "body_raw_contains",
                "field": "body",
                "ok": text in actual["body_raw"],
                "expected": text,
                "hint": "body_missing_text",
                "hint_params": {"text": text},
            }
        )
    if expected.get("body"):
        body_checks = check_body(actual, expected["body"])
        names = {c["name"] for c in checks}
        checks.extend(c for c in body_checks if c["name"] not in names)
    return checks


def validate(
    actual: RequestSnapshot,
    expected: Mapping[str, Any],
    task_hints: Mapping[str, str] | None = None,
) -> Result:
    """Проверить один запрос против эталона (без учёта истории попыток)."""
    checks = run_checks(actual, expected)
    passed = bool(checks) and all(c["ok"] for c in checks)
    return finalize(passed, checks, task_hints or {})


def finalize(passed: bool, checks: list[Check], task_hints: Mapping[str, str]) -> Result:
    hints = [] if passed else build_hints(checks, task_hints)
    public = [{k: v for k, v in c.items() if k not in ("hint", "hint_params")} for c in checks]
    return {"passed": passed, "checks": public, "hints": hints}
