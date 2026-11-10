"""Учебная авторизация (глава 4): /api/auth/*, /api/admin/users."""

import base64
from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.services import auth_tokens
from app.services.snapshot import mask_authorization

CREDS = {"username": "agent", "password": "support123"}


async def student(client: AsyncClient) -> dict[str, str]:
    code = (await client.get("/api/room")).json()["me"]["student_code"]
    return {"X-Student-Id": code}


async def login(postman: AsyncClient, h: dict[str, str], **extra: object) -> str:
    r = await postman.post("/api/auth/login", json={**CREDS, **extra}, headers=h)
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


def bearer(token: str, h: dict[str, str] | None = None) -> dict[str, str]:
    return {**(h or {}), "Authorization": f"Bearer {token}"}


def basic(user: str, password: str) -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


async def test_me_without_credentials(postman: AsyncClient) -> None:
    r = await postman.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"] == "missing_credentials"
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_login_and_me_with_bearer(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    r = await postman.post("/api/auth/login", json=CREDS, headers=h)
    body = r.json()
    assert r.status_code == 200
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    assert body["access_token"].startswith("tok_")
    r = await postman.get("/api/auth/me", headers=bearer(body["access_token"]))
    assert r.status_code == 200
    me = r.json()
    assert (me["username"], me["role"], me["auth"]) == ("agent", "agent", "bearer")
    assert me["expires_at"].endswith("Z")


async def test_login_errors(postman: AsyncClient) -> None:
    r = await postman.post("/api/auth/login", json={"username": "agent", "password": "x"})
    assert (r.status_code, r.json()["error"]) == (401, "invalid_credentials")
    r = await postman.post("/api/auth/login", json={"username": "agent"})
    assert r.status_code == 422 and r.json()["details"]["missing"] == ["password"]
    for ttl in (1, 5000, "10", True):
        r = await postman.post("/api/auth/login", json={**CREDS, "expires_in": ttl})
        assert r.status_code == 422, ttl
        assert "expires_in" in r.json()["details"]["invalid"]
    r = await postman.post("/api/auth/login", content="x", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


@pytest.mark.parametrize(
    ("header", "error"),
    [
        ("Bearer", "malformed_authorization"),
        ("Bearer: {tok}", "malformed_authorization"),
        ('Bearer "{tok}"', "malformed_authorization"),
        ("{tok}", "malformed_authorization"),
        ("Token {tok}", "malformed_authorization"),
        ("Basic !!!", "malformed_authorization"),
        ("Bearer tok_doesnotexist", "invalid_token"),
        ("Bearer {short}", "invalid_token"),
    ],
)
async def test_bad_authorization_header(postman: AsyncClient, header: str, error: str) -> None:
    tok = await login(postman, {})
    value = header.format(tok=tok, short=tok[:-3])
    r = await postman.get("/api/auth/me", headers={"Authorization": value})
    assert r.status_code == 401, value
    assert r.json()["error"] == error
    assert "www-authenticate" in r.headers


async def test_token_in_query_is_explained(postman: AsyncClient) -> None:
    tok = await login(postman, {})
    r = await postman.get("/api/auth/me", params={"access_token": tok})
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "missing_credentials"
    assert body["details"]["query_param"] == "access_token"


async def test_basic_auth(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    r = await postman.get("/api/auth/me", headers={**h, **basic("agent", "support123")})
    assert r.status_code == 200 and r.json()["auth"] == "basic"
    assert r.json()["expires_at"] is None
    r = await postman.get("/api/auth/me", headers={**h, **basic("agent", "wrong")})
    assert (r.status_code, r.json()["error"]) == (401, "invalid_credentials")


async def test_api_key(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    tok = await login(postman, h)
    r = await postman.post("/api/auth/api-keys", headers=bearer(tok, h))
    assert r.status_code == 201
    key = r.json()["api_key"]
    assert key.startswith("key_")
    r = await postman.get("/api/auth/me", headers={"X-API-Key": key})
    assert r.status_code == 200 and r.json()["auth"] == "api_key"
    # Перепутанные места: ключ как Bearer и токен как X-API-Key.
    r = await postman.get("/api/auth/me", headers=bearer(key))
    assert r.json()["error"] == "invalid_token" and "X-API-Key" in r.json()["message"]
    r = await postman.get("/api/auth/me", headers={"X-API-Key": tok})
    assert r.json()["error"] == "invalid_token"
    r = await postman.get("/api/auth/me", params={"api_key": key})
    assert r.json()["details"]["query_param"] == "api_key"


async def test_admin_requires_role(postman: AsyncClient) -> None:
    tok = await login(postman, {})
    r = await postman.get("/api/admin/users", headers=bearer(tok))
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "insufficient_role"
    assert body["details"] == {"required_role": "admin", "your_role": "agent"}
    r = await postman.get("/api/admin/users")
    assert r.status_code == 401


async def test_token_expires(postman: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tok = await login(postman, {}, expires_in=10)
    assert (await postman.get("/api/auth/me", headers=bearer(tok))).status_code == 200
    later = auth_tokens.now() + timedelta(seconds=11)
    monkeypatch.setattr(auth_tokens, "now", lambda: later)
    r = await postman.get("/api/auth/me", headers=bearer(tok))
    assert (r.status_code, r.json()["error"]) == (401, "token_expired")
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


async def test_change_password_revokes_tokens(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    old = await login(postman, h)
    r = await postman.post("/api/auth/api-keys", headers=bearer(old, h))
    key = r.json()["api_key"]
    change = {"old_password": "support123", "new_password": "newpass42"}
    r = await postman.post("/api/auth/change-password", json=change, headers=bearer(old, h))
    assert r.status_code == 200 and r.json()["revoked"] == 2
    for headers in (bearer(old), {"X-API-Key": key}):
        r = await postman.get("/api/auth/me", headers=headers)
        assert (r.status_code, r.json()["error"]) == (401, "token_revoked")
    r = await postman.post("/api/auth/login", json=CREDS, headers=h)
    assert r.status_code == 401
    new = await login(postman, h, password="newpass42")
    assert (await postman.get("/api/auth/me", headers=bearer(new))).status_code == 200
    # Пароль у каждого ученика свой: в песочнице старый по-прежнему работает.
    await login(postman, {})
    # Сброс: пароль по умолчанию, токены отозваны.
    r = await postman.post("/api/auth/reset", headers=h)
    assert r.status_code == 200 and r.json()["revoked"] == 1
    assert (await postman.get("/api/auth/me", headers=bearer(new))).status_code == 401
    await login(postman, h)


async def test_change_password_errors(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    tok = await login(postman, h)
    url = "/api/auth/change-password"
    r = await postman.post(
        url, json={"old_password": "x", "new_password": "newpass42"}, headers=bearer(tok, h)
    )
    assert (r.status_code, r.json()["error"]) == (400, "invalid_old_password")
    r = await postman.post(
        url, json={"old_password": "support123", "new_password": "123"}, headers=bearer(tok, h)
    )
    assert r.status_code == 422 and "new_password" in r.json()["details"]["invalid"]
    r = await postman.post(url, json={"old_password": "support123"}, headers=bearer(tok, h))
    assert r.status_code == 422
    # Песочница: менять общий пароль нельзя.
    sandbox = await login(postman, {})
    r = await postman.post(
        url,
        json={"old_password": "support123", "new_password": "newpass42"},
        headers=bearer(sandbox),
    )
    assert (r.status_code, r.json()["error"]) == (400, "student_required")
    # Токен песочницы с чужим X-Student-Id.
    r = await postman.post(
        url,
        json={"old_password": "support123", "new_password": "newpass42"},
        headers=bearer(sandbox, h),
    )
    assert (r.status_code, r.json()["error"]) == (403, "foreign_account")
    assert (await postman.post("/api/auth/reset")).status_code == 400


async def test_errors_in_english(postman: AsyncClient) -> None:
    r = await postman.get("/api/auth/me", headers={"Accept-Language": "en"})
    assert r.json()["message"].startswith("Authorization required")


async def test_journal_shows_secrets_partially(client: AsyncClient, postman: AsyncClient) -> None:
    h = await student(client)
    tok = await login(postman, h)
    key = (await postman.post("/api/auth/api-keys", headers=bearer(tok, h))).json()["api_key"]
    await postman.get("/api/auth/me", headers=bearer(tok, h))
    await postman.get("/api/auth/me", headers={**h, **basic("agent", "support123")})
    await postman.get("/api/auth/me", headers={**h, "X-API-Key": key})
    await postman.get("/api/auth/me", headers={**h, "Authorization": tok})  # без Bearer
    r = await client.get("/api/journal")
    # Полные токен и ключ есть только в телах ответов login / api-keys — так и задумано.
    headers_text = str([e["headers"] for e in r.json()["items"]])
    assert tok not in headers_text and key not in headers_text
    shown = [
        e["headers"].get("authorization") or e["headers"].get("x-api-key")
        for e in r.json()["items"]
        if e["path"] == "/api/auth/me"
    ]
    assert f"Bearer {tok[:6]}…{tok[-2:]}" in shown
    assert "Basic ***" in shown
    assert f"{key[:6]}…{key[-2:]}" in shown
    assert f"{tok[:6]}…{tok[-2:]}" in shown


async def test_echo_hides_secrets_fully(postman: AsyncClient) -> None:
    r = await postman.get(
        "/api/echo",
        headers={
            "Authorization": "Bearer tok_0123456789abcdef",
            "X-API-Key": "key_0123456789abcdef",
        },
    )
    headers = r.json()["headers"]
    assert headers["authorization"] == "***" and headers["x-api-key"] == "***"


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("Bearer tok_3fabcdef0123456789a", "Bearer tok_3f…9a"),
        ("Bearer", "Bearer"),
        ("Bearer short", "Bearer ***"),
        ("Basic YWdlbnQ6c3VwcG9ydDEyMw==", "Basic ***"),
        ("tok_3fabcdef0123456789a", "tok_3f…9a"),
        ('Bearer "tok_3fabcdef0123456789a"', 'Bearer "tok_3…a"'),
    ],
)
def test_mask_authorization(value: str, shown: str) -> None:
    assert mask_authorization(value) == shown
