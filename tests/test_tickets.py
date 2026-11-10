from httpx import AsyncClient


async def _create(client: AsyncClient, **fields: str) -> dict[str, object]:
    payload = {"title": "Не работает кнопка", "priority": "high", **fields}
    r = await client.post("/api/tickets", json=payload)
    assert r.status_code == 201, r.text
    data: dict[str, object] = r.json()
    return data


async def test_create_and_get(client: AsyncClient) -> None:
    t = await _create(client)
    assert t["id"] and t["status"] == "open"
    r = await client.get(f"/api/tickets/{t['id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "Не работает кнопка"


async def test_create_requires_json_content_type(client: AsyncClient) -> None:
    r = await client.post("/api/tickets", content="title=x", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert r.json()["error"] == "unsupported_media_type"


async def test_create_invalid_json(client: AsyncClient) -> None:
    r = await client.post(
        "/api/tickets",
        content='{"title": "Ошибка", "priority": high}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_json"


async def test_create_missing_fields(client: AsyncClient) -> None:
    r = await client.post("/api/tickets", json={"description": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error"
    assert body["details"]["missing"] == ["title", "priority"]


async def test_create_bad_priority_and_title(client: AsyncClient) -> None:
    r = await client.post("/api/tickets", json={"title": "", "priority": "urgent"})
    assert r.status_code == 422
    assert set(r.json()["details"]["invalid"]) == {"title", "priority"}
    r = await client.post("/api/tickets", json={"title": "x" * 201, "priority": "low"})
    assert r.status_code == 422


async def test_list_with_filters(client: AsyncClient) -> None:
    a = await _create(client, title="A")
    await _create(client, title="B")
    await client.patch(f"/api/tickets/{a['id']}", json={"status": "closed"})
    r = await client.get("/api/tickets", params={"status": "open", "limit": 10})
    titles = [t["title"] for t in r.json()["items"]]
    assert titles == ["B"]
    r = await client.get("/api/tickets", params={"limit": 1})
    assert r.json()["count"] == 1
    r = await client.get("/api/tickets", params={"status": "weird"})
    assert r.status_code == 422


async def test_put_replaces(client: AsyncClient) -> None:
    t = await _create(client, description="старое")
    r = await client.put(f"/api/tickets/{t['id']}", json={"title": "Новое", "priority": "low"})
    assert r.status_code == 200
    d = r.json()
    assert (d["title"], d["priority"], d["description"], d["status"]) == (
        "Новое",
        "low",
        "",
        "open",
    )
    r = await client.put(f"/api/tickets/{t['id']}", json={"title": "Только title"})
    assert r.status_code == 422


async def test_patch_partial(client: AsyncClient) -> None:
    t = await _create(client)
    r = await client.patch(f"/api/tickets/{t['id']}", json={"priority": "low"})
    assert r.status_code == 200
    assert r.json()["priority"] == "low"
    assert r.json()["title"] == "Не работает кнопка"


async def test_delete_and_404(client: AsyncClient) -> None:
    t = await _create(client)
    assert (await client.delete(f"/api/tickets/{t['id']}")).status_code == 204
    r = await client.get(f"/api/tickets/{t['id']}")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
    assert (await client.delete("/api/tickets/9999")).status_code == 404


# ---------- Тикеты по ученику (X-Student-Id), пагинация, 409, сброс ----------


async def _student(client: AsyncClient) -> dict[str, str]:
    """Личный код пользователя сайта → заголовок для запросов «из Postman»."""
    r = await client.get("/api/room")
    code = r.json()["me"]["student_code"]
    assert len(code) == 6 and code.isalnum() and code.isupper()
    return {"X-Student-Id": code}


async def test_student_gets_seed_set(client: AsyncClient, postman: AsyncClient) -> None:
    h = await _student(client)
    r = await postman.get("/api/tickets", headers=h)
    body = r.json()
    assert (body["page"], body["limit"], body["total"], body["pages"]) == (1, 10, 23, 3)
    assert body["count"] == len(body["items"]) == 10
    titles = [t["title"] for t in body["items"]]
    assert "SMS code not received" not in titles
    r = await postman.get("/api/tickets", params={"page": 2, "limit": 10}, headers=h)
    assert "SMS code not received" in [t["title"] for t in r.json()["items"]]
    r = await postman.get("/api/tickets", params={"page": 3}, headers=h)
    assert r.json()["count"] == 3
    r = await postman.get("/api/tickets", params={"page": 9}, headers=h)
    assert r.json()["items"] == [] and r.json()["total"] == 23
    r = await postman.get("/api/tickets", params={"status": "closed", "limit": 100}, headers=h)
    assert r.json()["total"] >= 1
    assert (await postman.get("/api/tickets", params={"page": 0}, headers=h)).status_code == 422
    # Нижний регистр и пробелы в коде допустимы.
    lower = {"X-Student-Id": f" {h['X-Student-Id'].lower()} "}
    assert (await postman.get("/api/tickets", headers=lower)).json()["total"] == 23


async def test_tickets_are_isolated(client: AsyncClient, postman: AsyncClient) -> None:
    h = await _student(client)
    mine = (await postman.get("/api/tickets", headers=h)).json()["items"][0]
    # Песочница (без кода и с неизвестным кодом) не видит тикеты ученика.
    for headers in ({}, {"X-Student-Id": "ZZZZZZ"}, {"X-Student-Id": "bad"}):
        r = await postman.get("/api/tickets", headers=headers)
        assert r.json()["total"] == 0
        r = await postman.get(f"/api/tickets/{mine['id']}", headers=headers)
        assert r.status_code == 404
    # Новый тикет песочницы ученику не виден, и наоборот.
    sandbox = await _create(postman)
    r = await postman.get(f"/api/tickets/{sandbox['id']}", headers=h)
    assert r.status_code == 404
    r = await postman.post("/api/tickets", json={"title": "Мой", "priority": "low"}, headers=h)
    assert r.status_code == 201
    assert (await postman.get("/api/tickets", headers=h)).json()["total"] == 24
    assert (await postman.get("/api/tickets")).json()["total"] == 1


async def test_seed_once_and_reset(client: AsyncClient, postman: AsyncClient) -> None:
    h = await _student(client)
    items = (await postman.get("/api/tickets", params={"limit": 100}, headers=h)).json()["items"]
    for t in items:
        assert (await postman.delete(f"/api/tickets/{t['id']}", headers=h)).status_code == 204
    # Всё удалили — набор сам не возвращается.
    assert (await postman.get("/api/tickets", headers=h)).json()["total"] == 0
    r = await postman.post("/api/tickets/reset", headers=h)
    assert r.status_code == 200
    assert r.json() == {"reset": True, "total": 23}
    r = await postman.get("/api/tickets", params={"limit": 100}, headers=h)
    assert [t["title"] for t in r.json()["items"]] == [t["title"] for t in items]
    r = await postman.post("/api/tickets/reset")
    assert r.status_code == 400
    assert r.json()["error"] == "student_required"


async def test_closed_ticket_conflict(client: AsyncClient, postman: AsyncClient) -> None:
    h = await _student(client)
    r = await postman.get("/api/tickets", params={"status": "closed"}, headers=h)
    t = r.json()["items"][0]
    url = f"/api/tickets/{t['id']}"
    r = await postman.patch(url, json={"priority": "high"}, headers=h)
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "ticket_closed"
    assert '{"status": "open"}' in body["message"]
    r = await postman.put(url, json={"title": "x", "priority": "low", "status": "open"}, headers=h)
    assert r.status_code == 409
    r = await postman.patch(url, json={"status": "in_progress"}, headers=h)
    assert r.status_code == 409
    # Открыть можно; дальше — обычные правки.
    r = await postman.patch(url, json={"status": "open"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "open"
    r = await postman.put(url, json={"title": "Новое", "priority": "low"}, headers=h)
    assert r.status_code == 200
    # Закрыть открытый — можно; невалидное тело на закрытом — 422 раньше 409.
    assert (await postman.patch(url, json={"status": "closed"}, headers=h)).status_code == 200
    r = await postman.put(url, json={"title": "Только title"}, headers=h)
    assert r.status_code == 422
    # Удалить закрытый можно.
    assert (await postman.delete(url, headers=h)).status_code == 204


async def test_conflict_message_in_english(client: AsyncClient, postman: AsyncClient) -> None:
    t = await _create(postman)
    await postman.patch(f"/api/tickets/{t['id']}", json={"status": "closed"})
    r = await postman.patch(f"/api/tickets/{t['id']}", json={"title": "x"})
    assert r.status_code == 409
    assert r.json()["message"].startswith(f"Ticket {t['id']} is closed")
