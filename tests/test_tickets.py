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
