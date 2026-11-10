"""Сквозная проверка контента: настоящий сервер + настоящий checker.js.

Для каждого задания фазы 1 (во всех главах) отправляем эталонное решение (и типичные ошибки)
на учебный API, берём ответы сервера и прогоняем их через тот же checker.js,
что работает в браузере. Так ловим задания, которые нельзя решить или
которые засчитываются за неправильный запрос.

Фаза 2: запросы идут «из Postman» (без cookie) с заголовками X-Student-Id и X-Task-Code,
а история для checker.js берётся из журнала ученика (`GET /api/journal`) — как на
странице главы.
"""

import asyncio
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


def _tasks(files: list[TasksFile]) -> dict[str, dict[str, Any]]:
    return {t.id: t.model_dump() for f in files for t in f.tasks if t.phase in (1, 2)}


# Все главы, а не только ch01: задание без эталонного решения роняет
# test_every_phase1_task_has_solution / test_every_phase2_task_has_solution.
TASKS_BY_LANG = {
    SOURCE_LANG: _tasks(load_task_files(CONTENT_DIR)),
    **{
        lang: _tasks(list(by_chapter.values()))
        for lang, by_chapter in load_task_translations(CONTENT_DIR).items()
    },
}
TASKS = {k: v for k, v in TASKS_BY_LANG[SOURCE_LANG].items() if v["phase"] == 1}
PHASE2_TASKS = {k: v for k, v in TASKS_BY_LANG[SOURCE_LANG].items() if v["phase"] == 2}
CYRILLIC = re.compile(r"[А-Яа-яЁё]")

pytestmark = pytest.mark.skipif(NODE is None, reason="нужен Node.js для запуска checker.js")

JSON_CT = {"Content-Type": "application/json"}
TICKET = '{"ticket_id": "123", "message": "Не работает кнопка сохранения", "priority": "high"}'
TYPES = (
    '{"ticket_id": "123", "status": "open", "priority": 2, "urgent": true,'
    ' "tags": ["billing", "mobile"]}'
)
ACCEPT_AUTH = {"Accept": "application/json", "Authorization": "Bearer test-token-123"}
BROKEN_TWO = "{'title': 'Не могу войти', 'priority': 'high',}"
FIXED_TWO = '{"title": "Не могу войти", "priority": "high"}'

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
    "ch01-task3": [{"url": "/api/echo?status=open&limit=10"}],
    "ch01-task4": [
        {"url": "/api/echo?source=postman?user=student"},
        {"url": "/api/echosource=postman"},
        {"url": "/api/echo?source=postman&user=student"},
    ],
    "ch01-task5": [{"url": "/api/echo?stauts=open"}, {"url": "/api/echo?status=open"}],
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
    "ch02-task6": [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": TYPES}],
    "ch02-task7": [
        {
            "method": "POST",
            "url": "/api/echo",
            "headers": {**JSON_CT, **ACCEPT_AUTH},
            "body": TICKET,
        }
    ],
    "ch02-task8": [
        {"url": "/api/status/503"},
        {"url": "/api/status/201"},
        {"url": "/api/status/403"},
        {"url": "/api/status/401"},
    ],
    "ch02-task9": [
        {"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": BROKEN_TWO},
        {"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": FIXED_TWO},
    ],
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
    ("ch01-task3", [{"url": "/api/echo?status=open"}], "limit=10"),
    ("ch01-task3", [{"url": "/api/tickets?status=open&limit=10"}], "/api/echo"),
    (
        "ch01-task4",
        [{"url": "/api/echo?source=postman&user=student"}],
        "postman?user=student",
    ),
    (
        "ch01-task4",
        [{"url": "/api/echo?source=postman?user=student"}, {"url": "/api/echosource=postman"}],
        "исправленный",
    ),
    ("ch01-task5", [{"url": "/api/echo?status=open"}], "stauts"),
    (
        "ch01-task5",
        [{"url": "/api/echo?stauts=open"}, {"url": "/api/echo?stauts=open&status=open"}],
        "stauts",
    ),
    (
        "ch02-task6",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": TYPES.replace('"priority": 2', '"priority": "2"'),
            }
        ],
        "число",
    ),
    (
        "ch02-task6",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": TYPES.replace("true", '"true"'),
            }
        ],
        "true",
    ),
    (
        "ch02-task6",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": TYPES.replace('"123"', "123"),
            }
        ],
        "строка",
    ),
    (
        "ch02-task7",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": {**JSON_CT, "Authorization": "Bearer test-token-123"},
                "body": TICKET,
            }
        ],
        "Accept",
    ),
    (
        "ch02-task7",
        [
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": {**JSON_CT, "Accept": "application/json"},
                "body": TICKET,
            }
        ],
        "Authorization",
    ),
    ("ch02-task8", [{"url": "/api/status/201"}, {"url": "/api/status/401"}], "403"),
    (
        "ch02-task9",
        [
            {"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": BROKEN_TWO},
            {
                "method": "POST",
                "url": "/api/echo",
                "headers": JSON_CT,
                "body": BROKEN_TWO.replace(",}", "}"),
            },
        ],
        "обе ошибки",
    ),
    (
        "ch02-task9",
        [{"method": "POST", "url": "/api/echo", "headers": JSON_CT, "body": FIXED_TWO}],
        "воспроизведи",
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


@pytest.mark.parametrize("task_id", ["ch02-task4", "ch02-task7"])
async def test_console_task_needs_console(client: AsyncClient, task_id: str) -> None:
    history = await send_all(client, SOLUTIONS[task_id])
    result = evaluate(task_id, history, {"consoleOpenedAt": None})
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


# ---------- Фаза 2: настоящий Postman ----------
# url может содержать {id:<название>} — id тикета ученика с этим названием (ищется
# перед запросом, как ученик ищет его в списке). {"sleep": N} — пауза (ожидание Retry-After).

NEW_TICKET = '{"title": "Test ticket", "priority": "medium"}'
LOGIN = "{id:Cannot log in to my account}"
EMAIL = "{id:How do I change my email?}"
PROMO = "{id:Promo code does not work}"
PROMO_PUT_BAD = '{"title": "Promo code does not work", "status": "in_progress"}'
PROMO_PUT_OK = '{"title": "Promo code does not work", "priority": "low", "status": "in_progress"}'


def patch(url: str, body: str) -> Req:
    return {"method": "PATCH", "url": url, "headers": JSON_CT, "body": body}


def put(url: str, body: str) -> Req:
    return {"method": "PUT", "url": url, "headers": JSON_CT, "body": body}


PHASE2_SOLUTIONS: dict[str, list[Req]] = {
    "ch03-task1": [{"url": "/api/echo"}],
    "ch03-task2": [{"url": "/api/tickets"}],
    "ch03-task3": [
        {"method": "POST", "url": "/api/tickets", "headers": JSON_CT, "body": NEW_TICKET}
    ],
    "ch03-task4": [
        {"url": "/api/tickets"},
        patch(f"/api/tickets/{LOGIN}", '{"status": "in_progress"}'),
    ],
    "ch03-task5": [
        {"method": "POST", "url": "/api/tickets", "headers": JSON_CT, "body": NEW_TICKET},
        {"method": "DELETE", "url": "/api/tickets/{id:Test ticket}"},
        {"url": "/api/tickets/{last_deleted}"},
    ],
    "ch03-task6": [patch(f"/api/tickets/{EMAIL}", '{"priority": "high"}')],
    "ch03-task7": [{"url": "/api/tickets"}, {"url": "/api/tickets?page=2"}],
    "ch03-task8": [
        {"url": "/api/limited"},
        {"url": "/api/limited"},
        {"url": "/api/limited"},
        {"url": "/api/limited"},
        {"sleep": 1.1},
        {"url": "/api/limited"},
    ],
    "ch03-task9": [
        put(f"/api/tickets/{PROMO}", PROMO_PUT_BAD),
        put(f"/api/tickets/{PROMO}", PROMO_PUT_OK),
    ],
    "ch03-task10": [{"url": "/api/status/503"}],
}

PHASE2_MISTAKES: list[tuple[str, list[Req], str]] = [
    ("ch03-task1", [{"method": "POST", "url": "/api/echo"}], "GET"),
    ("ch03-task1", [{"url": "/api/ech0"}], "/api/echo"),
    ("ch03-task2", [{"url": "/api/echo"}], "items"),
    ("ch03-task3", [{"method": "POST", "url": "/api/tickets", "body": NEW_TICKET}], "Content-Type"),
    (
        "ch03-task3",
        [
            {
                "method": "POST",
                "url": "/api/tickets",
                "headers": JSON_CT,
                "body": '{"title": "Test ticket", "priority": "medium", "status": "closed"}',
            }
        ],
        "open",
    ),
    ("ch03-task4", [put(f"/api/tickets/{LOGIN}", '{"status": "in_progress"}')], "PUT"),
    (
        "ch03-task4",
        [
            put(
                f"/api/tickets/{LOGIN}",
                '{"title": "Cannot log in to my account", "priority": "high",'
                ' "status": "in_progress"}',
            )
        ],
        "PUT",
    ),
    ("ch03-task4", [patch(f"/api/tickets/{PROMO}", '{"status": "in_progress"}')], "не тот тикет"),
    ("ch03-task5", [{"url": "/api/tickets/999999"}], "удали"),
    ("ch03-task5", [{"method": "DELETE", "url": f"/api/tickets/{PROMO}"}], "GET"),
    ("ch03-task6", [patch(f"/api/tickets/{PROMO}", '{"priority": "high"}')], "409"),
    ("ch03-task7", [{"url": "/api/tickets"}], "page = 2"),
    ("ch03-task7", [{"url": "/api/tickets?page=2&limit=20"}], "limit"),
    ("ch03-task8", [{"url": "/api/limited"}, {"url": "/api/limited"}], "429"),
    (
        "ch03-task8",
        [{"url": "/api/limited"}] * 5,
        "Retry-After",
    ),
    ("ch03-task9", [put(f"/api/tickets/{PROMO}", PROMO_PUT_OK)], "воспроизведи"),
    (
        "ch03-task9",
        [put(f"/api/tickets/{PROMO}", PROMO_PUT_BAD), put(f"/api/tickets/{PROMO}", PROMO_PUT_BAD)],
        "details.missing",
    ),
    ("ch03-task10", [{"url": "/api/status/502"}], "503"),
    ("ch03-task10", [{"url": "/api/echo"}], "503"),
]

_ID_RE = re.compile(r"\{id:([^}]+)\}")


async def site_student_code(client: AsyncClient) -> str:
    code: str = (await client.get("/api/room")).json()["me"]["student_code"]
    return code


async def ticket_id(postman: AsyncClient, code: str, title: str) -> int:
    """Id тикета ученика по названию (запрос без X-Task-Code — в историю задания не входит)."""
    r = await postman.get("/api/tickets?limit=100", headers={"X-Student-Id": code})
    for t in r.json()["items"]:
        if t["title"] == title:
            return int(t["id"])
    return 999_999


def entry_response(entry: dict[str, Any]) -> dict[str, Any]:
    """Запись журнала → ответ для checker.js (как normalizeResponse в phase2.js)."""
    resp = entry["response"]
    text = resp["body"]
    body: Any = None
    if text.strip():
        try:
            body = json.loads(text)
        except ValueError:
            body = text
    return {"status": resp["status"], "headers": resp["headers"], "body": body}


async def run_phase2(
    client: AsyncClient,
    postman: AsyncClient,
    task_id: str,
    requests: list[Req],
    *,
    student_header: bool = True,
    task_header: bool = True,
) -> list[dict[str, Any]]:
    """Отправить запросы «из Postman» и вернуть историю задания из журнала ученика."""
    code = await site_student_code(client)
    deleted: int | None = None
    for req in requests:
        if "sleep" in req:
            await asyncio.sleep(req["sleep"])
            continue
        url = req["url"]
        for title in _ID_RE.findall(url):
            url = url.replace(f"{{id:{title}}}", str(await ticket_id(postman, code, title)))
        url = url.replace("{last_deleted}", str(deleted))
        headers = dict(req.get("headers") or {})
        if student_header:
            headers["X-Student-Id"] = code
        if task_header:
            headers["X-Task-Code"] = task_id
        method = req.get("method", "GET")
        await postman.request(method, url, headers=headers, content=req.get("body"))
        if method == "DELETE":
            deleted = int(url.rsplit("/", 1)[1])
    items = (await client.get("/api/journal")).json()["items"]
    return [entry_response(e) for e in items if e["task_code"] == task_id]


@pytest.fixture
def short_limit() -> Any:
    """Окно /api/limited — 1 с вместо 10, чтобы не ждать Retry-After в тестах."""
    from app.services import limited

    old = limited.window.window
    limited.window.window = 1.0
    yield
    limited.window.window = old


def test_every_phase2_task_has_solution() -> None:
    assert set(PHASE2_SOLUTIONS) == set(PHASE2_TASKS)


@pytest.mark.parametrize("lang", [SOURCE_LANG, "en"])
@pytest.mark.parametrize("task_id", sorted(PHASE2_SOLUTIONS))
async def test_phase2_solution_passes(
    client: AsyncClient, postman: AsyncClient, short_limit: Any, task_id: str, lang: str
) -> None:
    history = await run_phase2(client, postman, task_id, PHASE2_SOLUTIONS[task_id])
    result = evaluate(task_id, history, lang=lang)
    assert result["passed"] is True, result


@pytest.mark.parametrize("missing", ["student", "task"])
@pytest.mark.parametrize("task_id", sorted(PHASE2_SOLUTIONS))
async def test_phase2_needs_both_headers(
    client: AsyncClient, postman: AsyncClient, short_limit: Any, task_id: str, missing: str
) -> None:
    """Эталон без одного из заголовков не засчитывается: в истории задания пусто."""
    history = await run_phase2(
        client,
        postman,
        task_id,
        PHASE2_SOLUTIONS[task_id],
        student_header=missing != "student",
        task_header=missing != "task",
    )
    assert history == []
    assert evaluate(task_id, history)["passed"] is False


@pytest.mark.parametrize(("task_id", "requests", "hint_part"), PHASE2_MISTAKES)
async def test_phase2_mistake_fails_with_hint(
    client: AsyncClient,
    postman: AsyncClient,
    short_limit: Any,
    task_id: str,
    requests: list[Req],
    hint_part: str,
) -> None:
    history = await run_phase2(client, postman, task_id, requests)
    result = evaluate(task_id, history)
    assert result["passed"] is False
    assert hint_part in result["hint"], result["hint"]
    en = evaluate(task_id, history, lang="en")
    assert en["passed"] is False and en["hint"]
    assert not CYRILLIC.search(en["hint"]), en["hint"]
