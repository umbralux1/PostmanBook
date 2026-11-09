"""Фаза 3: проверка ответа внешнего API, который пользователь вставил в форму.

Пользователь копирует из Postman тело ответа (JSON) — иногда вместе со
строкой статуса и заголовками. Мы разбираем текст и проверяем его по
секции `expected.response` задания::

    expected:
      response:
        status: 200
        required_keys: [args, headers]
        json_fields:
          args.source: postman
"""

import json
import re
from collections.abc import Mapping
from typing import Any

from app.services.validator import Check, Result, finalize

_STATUS_RE = re.compile(r"^\s*(?:HTTP/[\d.]+\s+)?(\d{3})(?:\s+[^\n{]*)?$")
_MISSING = object()


def parse_pasted_response(raw: str) -> dict[str, Any]:
    """Вернуть {"status": int|None, "headers": {...}, "json": Any, "parsed": bool}."""
    text = raw.strip().lstrip("﻿")
    status: int | None = None
    headers: dict[str, str] = {}

    try:
        return {"status": None, "headers": {}, "json": json.loads(text), "parsed": True}
    except ValueError:
        pass

    body_start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    head = text[:body_start] if body_start >= 0 else text
    for line in head.splitlines():
        if not line.strip():
            continue
        m = _STATUS_RE.match(line)
        if m and status is None:
            status = int(m.group(1))
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    if body_start < 0:
        return {"status": status, "headers": headers, "json": None, "parsed": False}
    try:
        data = json.loads(text[body_start:])
    except ValueError:
        return {"status": status, "headers": headers, "json": None, "parsed": False}
    return {"status": status, "headers": headers, "json": data, "parsed": True}


def _get_path(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def check_external_response(
    raw: str, expected: Mapping[str, Any], task_hints: Mapping[str, str]
) -> Result:
    spec: Mapping[str, Any] = expected.get("response", {})
    parsed = parse_pasted_response(raw)
    checks: list[Check] = [
        {"name": "parsed", "field": "body", "ok": parsed["parsed"], "hint": "unparseable_response"}
    ]
    if not parsed["parsed"]:
        return finalize(False, checks, task_hints)

    data = parsed["json"]
    if "status" in spec and parsed["status"] is not None:
        checks.append(
            {
                "name": "status",
                "field": "status",
                "ok": parsed["status"] == int(spec["status"]),
                "expected": int(spec["status"]),
                "actual": parsed["status"],
                "hint": "wrong_status",
            }
        )
    for key in spec.get("required_keys", []):
        found = _get_path(data, str(key)) is not _MISSING
        checks.append(
            {
                "name": f"key:{key}",
                "field": "body",
                "ok": found,
                "hint": "missing_response_field",
                "hint_params": {"field": key},
            }
        )
    for key, value in (spec.get("json_fields") or {}).items():
        got = _get_path(data, str(key))
        checks.append(
            {
                "name": f"field:{key}",
                "field": "body",
                "ok": got is not _MISSING and got == value,
                "expected": value,
                "actual": None if got is _MISSING else got,
                "hint": "missing_response_field" if got is _MISSING else "wrong_response_field",
                "hint_params": {"field": key},
            }
        )
    passed = all(c["ok"] for c in checks)
    return finalize(passed, checks, task_hints)
