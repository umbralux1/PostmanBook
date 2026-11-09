"""Серверный валидатор запросов — используется для фазы 2 (запросы из Postman)."""

import json
from typing import Any

import pytest

from app.services.hints import render
from app.services.snapshot import make_snapshot
from app.services.validator import path_matches, validate

JSON_CT = {"Content-Type": "application/json"}
EXPECTED: dict[str, Any] = {
    "method": "POST",
    "path": "/api/echo",
    "query": {"source": "postman"},
    "headers": {"content-type": "application/json", "x-debug-source": "support-training"},
    "body": {
        "json_schema": {
            "type": "object",
            "required": ["ticket_id", "priority"],
            "properties": {"priority": {"type": "string", "enum": ["low", "medium", "high"]}},
        }
    },
}
HINTS = {"wrong_method": "Нужен POST.", "missing_query": "Нет параметра {{param}}."}
GOOD_HEADERS = {**JSON_CT, "X-Debug-Source": "support-training"}
GOOD_BODY = json.dumps({"ticket_id": "1", "priority": "high"})


def by_name(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in result["checks"]}


def test_passes() -> None:
    snap = make_snapshot("POST", "/api/echo", {"source": "postman"}, GOOD_HEADERS, GOOD_BODY)
    result = validate(snap, EXPECTED, HINTS)
    assert result["passed"] is True and result["hints"] == []


def test_wrong_method_and_missing_query_use_task_hints() -> None:
    snap = make_snapshot("GET", "/api/echo", {}, GOOD_HEADERS, GOOD_BODY)
    result = validate(snap, EXPECTED, HINTS)
    assert result["passed"] is False
    assert "Нужен POST." in result["hints"]
    assert "Нет параметра source." in result["hints"]


def test_content_type_with_charset_is_ok() -> None:
    headers = {**GOOD_HEADERS, "Content-Type": "application/json; charset=utf-8"}
    snap = make_snapshot("POST", "/api/echo", {"source": "postman"}, headers, GOOD_BODY)
    assert by_name(validate(snap, EXPECTED))["content_type"]["ok"] is True


def test_missing_header_default_hint() -> None:
    snap = make_snapshot("POST", "/api/echo", {"source": "postman"}, JSON_CT, GOOD_BODY)
    result = validate(snap, EXPECTED)
    assert by_name(result)["header:x-debug-source"]["ok"] is False
    assert "Не хватает заголовка: x-debug-source." in result["hints"]


def test_invalid_json_and_missing_fields() -> None:
    snap = make_snapshot("POST", "/api/echo", {"source": "postman"}, GOOD_HEADERS, '{"a": 1,}')
    assert by_name(validate(snap, EXPECTED))["body_valid_json"]["ok"] is False
    snap = make_snapshot(
        "POST", "/api/echo", {"source": "postman"}, GOOD_HEADERS, '{"priority": "low"}'
    )
    check = by_name(validate(snap, EXPECTED))["body_required_fields"]
    assert check["ok"] is False and check["missing"] == ["ticket_id"]


def test_enum_violation() -> None:
    body = json.dumps({"ticket_id": "1", "priority": "urgent"})
    snap = make_snapshot("POST", "/api/echo", {"source": "postman"}, GOOD_HEADERS, body)
    assert by_name(validate(snap, EXPECTED))["body_schema"]["ok"] is False


@pytest.mark.parametrize(
    ("pattern", "path", "ok"),
    [
        ("/api/status/{{code}}", "/api/status/404", True),
        ("/api/status/{{ code }}", "/api/status/500", True),
        ("/api/status/{{code}}", "/api/status/404/x", False),
        ("/api/echo", "/api/echo/", True),
        ("/api/echo", "/api/echoes", False),
    ],
)
def test_path_matches(pattern: str, path: str, ok: bool) -> None:
    assert path_matches(pattern, path) is ok


def test_hint_render_is_plain_substitution() -> None:
    assert render("Нет {{param}} и {{ other }}", {"param": "user"}) == "Нет user и {{ other }}"
    assert render("{{x}}", {"x": "{{__class__}}"}) == "{{__class__}}"


def test_validate_empty_expected_never_passes() -> None:
    assert validate(make_snapshot("GET", "/"), {})["passed"] is False
