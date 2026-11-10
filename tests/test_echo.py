from httpx import AsyncClient

from app.api.echo import ALLOWED_STATUS_CODES


async def test_echo_get_returns_args_and_headers(client: AsyncClient) -> None:
    r = await client.get(
        "/api/echo",
        params={"source": "postman", "user": "student"},
        headers={"X-Debug-Source": "support-training"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["method"] == "GET"
    assert data["path"] == "/api/echo"
    assert data["args"] == {"source": "postman", "user": "student"}
    assert data["headers"]["x-debug-source"] == "support-training"
    assert data["task_code"] is None
    assert data["received_at"].endswith("Z")


async def test_echo_post_json(client: AsyncClient) -> None:
    r = await client.post("/api/echo", json={"ticket_id": "123"})
    assert r.status_code == 200
    assert r.json()["json"] == {"ticket_id": "123"}


async def test_echo_hides_cookie_and_authorization(client: AsyncClient) -> None:
    r = await client.get("/api/echo", headers={"Authorization": "Bearer secret"})
    headers = r.json()["headers"]
    assert headers["authorization"] == "***"
    assert "secret" not in r.text
    assert "test-session-token" not in r.text


async def test_echo_invalid_json_gives_400_in_common_format(client: AsyncClient) -> None:
    r = await client.post(
        "/api/echo", content='{"priority": high}', headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_json"
    assert set(body) == {"error", "message", "details"}


async def test_echo_returns_task_code_without_server_validation(client: AsyncClient) -> None:
    r = await client.get(
        "/api/echo?source=postman&user=student", headers={"X-Task-Code": "ch01-task1"}
    )
    data = r.json()
    assert data["task_code"] == "ch01-task1"
    # Фаза 1 проверяется на фронте по ответу — сервер вердикт не выносит.
    assert "validation" not in data


async def test_status_whitelist(client: AsyncClient) -> None:
    for code in (200, 404, 201, 429):
        r = await client.get(f"/api/status/{code}")
        assert r.status_code == code
        assert r.json() == {"status": code}
    assert (await client.get("/api/status/204")).status_code == 204
    assert 418 not in ALLOWED_STATUS_CODES


async def test_5xx_body_has_request_id(client: AsyncClient) -> None:
    for code in (500, 502, 503):
        r = await client.get(f"/api/status/{code}")
        assert r.status_code == code
        assert r.json() == {"status": code, "request_id": r.headers["x-request-id"]}


async def test_request_id_header(client: AsyncClient, postman: AsyncClient) -> None:
    r1 = await postman.get("/api/echo")
    r2 = await postman.get("/api/echo")
    rid = r1.headers["x-request-id"]
    assert len(rid) == 36 and rid != r2.headers["x-request-id"]
    # Свой номер клиента возвращается как есть; небезопасный — заменяется.
    r = await postman.get("/api/status/503", headers={"X-Request-ID": "support-42"})
    assert r.headers["x-request-id"] == "support-42"
    assert r.json()["request_id"] == "support-42"
    r = await postman.get("/api/echo", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["x-request-id"] != "bad id\twith spaces"
    # На ошибках и в остальных /api/* тоже; на страницах сайта — нет.
    assert "x-request-id" in (await postman.get("/api/tickets/999")).headers
    assert "x-request-id" in (await postman.get("/api/nope")).headers
    assert "x-request-id" not in (await client.get("/")).headers


async def test_status_not_in_whitelist(client: AsyncClient) -> None:
    for bad in ("418", "999", "abc"):
        r = await client.get(f"/api/status/{bad}")
        assert r.status_code == 400
        assert r.json()["error"] == "status_not_allowed"


async def test_cors_preflight(client: AsyncClient) -> None:
    r = await client.options(
        "/api/echo",
        headers={
            "Origin": "https://example.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-task-code",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "https://example.org")


async def test_unknown_route_common_error_format(client: AsyncClient) -> None:
    r = await client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


async def test_pages_render_and_set_cookie(postman: AsyncClient) -> None:
    r = await postman.get("/")
    assert r.status_code == 200
    assert "session_token" in r.headers.get("set-cookie", "")
    assert "httponly" in r.headers["set-cookie"].lower()
    r = await postman.get("/chapters/ch01")
    assert r.status_code == 200
    assert 'class="pm"' in r.text  # мини-Postman на странице
    assert "Parameters via the Params tab" in r.text
    assert 'href="/chapters/ch02"' in r.text  # ссылка на следующую главу
    r = await postman.get("/chapters/ch02")
    assert "Your first POST with JSON" in r.text
    assert 'href="/chapters/ch03"' in r.text
    # Глава фазы 2: вместо мини-Postman — панель «Your Postman».
    r = await postman.get("/chapters/ch03")
    assert 'class="pm"' in r.text and "Your Postman" in r.text
    assert "/partials/progress/ch03" in r.text
    # Глава без заданий: анонс, без блока «Tasks» и счётчика заданий.
    r = await postman.get("/chapters/ch04")
    assert r.status_code == 200
    assert "This chapter is in progress" in r.text
    assert "Tasks</h2>" not in r.text
    assert "/partials/progress/ch04" not in r.text
    r = await postman.get("/chapters/ch07")
    assert "Next chapter</div>" not in r.text  # глава 7 последняя
    r = await postman.get("/")
    assert r.text.count(">Coming soon<") == 4


async def test_api_does_not_issue_cookie(postman: AsyncClient) -> None:
    r = await postman.get("/api/echo")
    assert "set-cookie" not in r.headers


async def test_quiz_submission(client: AsyncClient) -> None:
    r = await client.post(
        "/chapters/ch02/quiz", data={"q1": "B", "q2": "C", "q3": "D", "q4": "B", "q5": "B"}
    )
    assert r.status_code == 200
    assert "5 of 5" in r.text
    r = await client.post(
        "/chapters/ch02/quiz", data={"q1": "A", "q2": "C", "q3": "D", "q4": "B", "q5": "B"}
    )
    assert "4 of 5" in r.text
