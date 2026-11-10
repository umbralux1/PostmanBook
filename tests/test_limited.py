from httpx import AsyncClient

from app.services.limited import SlidingWindow


async def test_limited_per_student(client: AsyncClient, postman: AsyncClient) -> None:
    code = (await client.get("/api/room")).json()["me"]["student_code"]
    h = {"X-Student-Id": code}
    for left in (2, 1, 0):
        r = await postman.get("/api/limited", headers=h)
        assert r.status_code == 200
        assert r.json()["remaining"] == left
        assert r.headers["x-ratelimit-remaining"] == str(left)
    r = await postman.get("/api/limited", headers=h)
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    retry = int(r.headers["retry-after"])
    assert 1 <= retry <= 10
    assert body["details"]["retry_after"] == retry
    assert "Retry-After" in body["message"]
    # Другой ученик и запрос без кода (по IP) считаются отдельно.
    assert (
        await postman.get("/api/limited", headers={"X-Student-Id": "ZZZZZZ"})
    ).status_code == 200
    assert (await postman.get("/api/limited")).status_code == 200


def test_sliding_window_frees_slots() -> None:
    now = [100.0]
    w = SlidingWindow(limit=3, window=10, clock=lambda: now[0])
    for _ in range(3):
        assert w.hit("a").allowed
        now[0] += 1
    d = w.hit("a")  # t=103, первый запрос был в t=100 → место освободится в t=110
    assert not d.allowed and d.retry_after == 7
    now[0] = 110.0
    assert w.hit("a").allowed
    assert not w.hit("a").allowed
