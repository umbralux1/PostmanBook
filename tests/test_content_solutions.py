"""Сквозная проверка контента: настоящий сервер + настоящий checker.js.

Для каждого задания фазы 1 (во всех главах) отправляем эталонное решение (и типичные ошибки)
на учебный API, берём ответы сервера и прогоняем их через тот же checker.js,
что работает в браузере. Так ловим задания, которые нельзя решить или
которые засчитываются за неправильный запрос.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.i18n import SOURCE_LANG
from app.services.task_loader import TasksFile, load_task_files, load_task_translations

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests/js/evaluate.cjs"
NODE = shutil.which("node")
CONTENT_DIR = ROOT / "app/content"


def _phase1(files: list[TasksFile]) -> dict[str, dict[str, Any]]:
    return {t.id: t.model_dump() for f in files for t in f.tasks if t.phase == 1}


# Все главы, а не только ch01: задание без эталонного решения роняет
# test_every_phase1_task_has_solution.
TASKS_BY_LANG = {
    SOURCE_LANG: _phase1(load_task_files(CONTENT_DIR)),
    **{
        lang: _phase1(list(by_chapter.values()))
        for lang, by_chapter in load_task_translations(CONTENT_DIR).items()
    },
}
TASKS = TASKS_BY_LANG[SOURCE_LANG]
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

pytestmark = pytest.mark.skipif(NODE is None, reason="нужен Node.js для запуска checker.js")

JSON_CT = {"Content-Type": "application/json"}
TICKET = '{"ticket_id": "123", "message": "Не работает кнопка сохранения", "priority": "high"}'

Req = dict[str, Any]


def evaluate(
    task_id: str,
    history: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
    lang: str = SOURCE_LANG,
) -> Any:
    expected = TASKS_BY_LANG[lang][task_id]["expected"]
    payload = json.dumps({"expected": expected, "history": history, "state": state or {}})
    out = subprocess.run(
        [NODE or "node", str(RUNNER)], input=payload, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def normalize(r: Response) -> dict[str, Any]:
    """То же, что TaskChecker.normalizeResponse в браузере."""
    try:
        body: Any = r.json() if r.content else None
    except ValueError:
        body = r.text
    return {"status": r.status_code, "headers": dict(r.headers), "body": body}


async def send_all(client: AsyncClient, requests: list[Req]) -> list[dict[str, Any]]:
    history = []
    for req in requests:
        r = await client.request(
            req.get("method", "GET"),
            req["url"],
            headers=req.get("headers"),
            content=req.get("body"),
        )
        history.append(normalize(r))
    return history


SOLUTIONS: dict[str, list[Req]] = {
    "ch01-task1": [{"url": "/api/echo?source=postman&user=student"}],
    "ch01-task2": [{"url": "/api/echo?source=postman&user=student&ticket_id=123&status=open"}],
    "ch02-task1": [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": TICKET}],
    "ch02-task2": [
        {
            "method": "POST",
            "url": "/api/echo",
            "headers": {**JSON_CT, "X-Debug-Source": "support-training"},
            "body": TICKET,
        }
    ],
    "ch02-task3": [
        {"url": "/api/status/404"},
        {"url": "/api/status/200"},
        {"url": "/api/status/500"},
    ],
    "ch02-task4": [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": TICKET}],
    "ch02-task5": [
        {
            "method": "POST",
            "url": "/api/echo",
            "headers": JSON_CT,
            "body": '{"title": "Ошибка", "priority": high}',
        },
        {
            "method": "POST",
            "url": "/api/echo",
            "headers": JSON_CT,
            "body": '{"title": "Ошибка", "priority": "high"}',
        },
    ],
}

# (задание, запросы, кусок ожидаемой подсказки)
MISTAKES: list[tuple[str, list[Req], str]] = [
    ("ch01-task1", [{"url": "/api/echo?source=postman"}], "user=student"),
    ("ch01-task1", [{"method": "POST", "url": "/api/echo?source=postman&user=student"}], "GET"),
    ("ch01-task1", [{"url": "/api/ech0?source=postman&user=student"}], "/api/echo"),
    ("ch01-task1", [{"url": "/api/echo?source=postman?user=student"}], "&"),
    ("ch01-task2", [{"url": "/api/echo?ticket_id=123&status=open"}], "source=postman"),
    ("ch02-task1", [{"method": "POST", "url": "/api/echo", "body": TICKET}], "Content-Type"),
    (
        "ch02-task1",
        [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": TICKET[:-1] + ",}"}],
        "JSON",
    ),
    (
        "ch02-task1",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": TICKET.replace('"123"', "123"),
            }
        ],
        "кавычках",
    ),
    ("ch02-task1", [{"url": "/api/echo", "headers": JSON_CT}], "POST"),
    (
        "ch02-task2",
        [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": TICKET}],
        "x-debug-source",
    ),
    ("ch02-task3", [{"url": "/api/status/200"}, {"url": "/api/status/500"}], "404"),
    ("ch02-task3", [{"url": "/api/nope"}], "/api/status/"),
    (
        "ch02-task5",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": '{"title": "Ошибка", "priority": "high"}',
            }
        ],
        "воспроизведи",
    ),
    (
        "ch02-task5",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": '{"title": "Ошибка", "priority": high}',
            }
        ],
        "исправь",
    ),
]


def test_every_phase1_task_has_solution() -> None:
    assert set(SOLUTIONS) == set(TASKS)


@pytest.mark.parametrize("task_id", sorted(SOLUTIONS))
async def test_solution_passes(client: AsyncClient, task_id: str) -> None:
    history = await send_all(client, SOLUTIONS[task_id])
    state = {"consoleOpenedAt": len(history)}  # Console открыли после запросов
    result = evaluate(task_id, history, state)
    assert result["passed"] is True, result


@pytest.mark.parametrize(("task_id", "requests", "hint_part"), MISTAKES)
async def test_mistake_fails_with_hint(
    client: AsyncClient, task_id: str, requests: list[Req], hint_part: str
) -> None:
    history = await send_all(client, requests)
    result = evaluate(task_id, history, {"consoleOpenedAt": len(history)})
    assert result["passed"] is False
    assert hint_part in result["hint"], result["hint"]


async def test_console_task_needs_console(client: AsyncClient) -> None:
    history = await send_all(client, SOLUTIONS["ch02-task4"])
    result = evaluate("ch02-task4", history, {"consoleOpenedAt": None})
    assert result["passed"] is False
    assert result["waitingConsole"] is True
    assert "Console" in result["hint"]


@pytest.mark.parametrize("task_id", sorted(SOLUTIONS))
async def test_solution_passes_in_english(client: AsyncClient, task_id: str) -> None:
    history = await send_all(client, SOLUTIONS[task_id])
    result = evaluate(task_id, history, {"consoleOpenedAt": len(history)}, lang="en")
    assert result["passed"] is True, result


@pytest.mark.parametrize(("task_id", "requests", "_hint"), MISTAKES)
async def test_mistake_fails_with_english_hint(
    client: AsyncClient, task_id: str, requests: list[Req], _hint: str
) -> None:
    history = await send_all(client, requests)
    result = evaluate(task_id, history, {"consoleOpenedAt": len(history)}, lang="en")
    assert result["passed"] is False
    assert result["hint"], "подсказка не должна быть пустой"
    assert not CYRILLIC.search(result["hint"]), result["hint"]
