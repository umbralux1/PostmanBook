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
    assert headers["authorization"] == "***скрыто***"
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
    for code in (200, 404, 500, 201, 429):
        r = await client.get(f"/api/status/{code}")
        assert r.status_code == code
        assert r.json() == {"status": code}
    assert (await client.get("/api/status/204")).status_code == 204
    assert 418 not in ALLOWED_STATUS_CODES


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
    assert "Your first POST with JSON" in r.text


async def test_api_does_not_issue_cookie(postman: AsyncClient) -> None:
    r = await postman.get("/api/echo")
    assert "set-cookie" not in r.headers


async def test_quiz_submission(client: AsyncClient) -> None:
    r = await client.post(
        "/chapters/ch01/quiz", data={"q1": "B", "q2": "C", "q3": "C", "q4": "B", "q5": "D"}
    )
    assert r.status_code == 200
    assert "5 of 5" in r.text
    r = await client.post(
        "/chapters/ch01/quiz", data={"q1": "A", "q2": "C", "q3": "C", "q4": "B", "q5": "D"}
    )
    assert "4 of 5" in r.text
