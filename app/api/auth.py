"""Учебный API: авторизация (глава 4) — /api/auth/*, /api/admin/users.

Три способа войти: `Authorization: Bearer <токен>` (токен из POST /api/auth/login),
`Authorization: Basic <base64 логин:пароль>` и `X-API-Key: <ключ>`. Ответ `me`
говорит, каким способом ученик вошёл (`auth`) — checker.js видит только ответ.

Ошибки `401` различаются полем `error`, чтобы по ответу было видно причину:
missing_credentials, malformed_authorization, invalid_token, token_expired,
token_revoked, invalid_credentials. `403 insufficient_role` — вход есть, прав нет.
"""

import base64
import binascii
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from sqlmodel import Session

from app.api.tickets import parse_json_body
from app.dependencies import SessionDep
from app.errors import ApiError
from app.i18n import N_, get_lang, translate
from app.models import AuthToken, User
from app.services import auth_tokens as at
from app.services.students import find_student

router = APIRouter(prefix="/api", tags=["training-api"])

REALM = 'Bearer realm="trainer"'
EXPECTED = "Authorization: Bearer <token>"
# Секрет в адресе вместо заголовка: частая ошибка (вкладка Params вместо Authorization).
QUERY_SECRETS = ("api_key", "apikey", "key", "access_token", "token")
STAFF = (
    {"username": "agent", "role": "agent"},
    {"username": "admin", "role": "admin"},
)


@dataclass
class Identity:
    username: str
    role: str
    auth: str  # bearer | basic | api_key
    owner: str | None
    token: AuthToken | None = None


def unauthorized(
    error: str,
    message: str,
    params: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> ApiError:
    challenge = REALM
    if error in ("invalid_token", "token_expired", "token_revoked"):
        challenge += ', error="invalid_token"'
    return ApiError(
        401, error, message, details, headers={"WWW-Authenticate": challenge}, params=params
    )


def malformed(message: str, params: dict[str, Any] | None = None) -> ApiError:
    return unauthorized("malformed_authorization", message, params, {"expected": EXPECTED})


def check_token(t: AuthToken | None, kind: str) -> AuthToken:
    """Токен или ключ существует, нужного вида, не отозван и не просрочен."""
    if t is not None and t.kind != kind:
        if kind == at.BEARER:
            raise unauthorized(
                "invalid_token",
                N_("Это API-ключ, а не токен: передайте его в заголовке X-API-Key."),
            )
        raise unauthorized(
            "invalid_token",
            N_(
                "Это токен, а не API-ключ: передайте его в заголовке Authorization: Bearer <токен>."
            ),
        )
    if t is None:
        if kind == at.BEARER:
            raise unauthorized(
                "invalid_token",
                N_(
                    "Такого токена нет. Проверьте, что он скопирован целиком и получен на этом же сайте: POST /api/auth/login."  # noqa: E501
                ),
            )
        raise unauthorized(
            "invalid_token",
            N_(
                "Такого API-ключа нет. Проверьте, что он скопирован целиком: POST /api/auth/api-keys."  # noqa: E501
            ),
        )
    if t.revoked_at is not None:
        raise unauthorized(
            "token_revoked",
            N_(
                "Токен отозван — например, после смены пароля. Войдите заново: POST /api/auth/login."  # noqa: E501
            ),
            details={"revoked_at": at.iso(t.revoked_at)},
        )
    if at.is_expired(t):
        raise unauthorized(
            "token_expired",
            N_("Срок действия токена истёк. Получите новый: POST /api/auth/login."),
            details={"expired_at": at.iso(t.expires_at)},
        )
    return t


def from_bearer(session: Session, value: str) -> Identity:
    if not value:
        raise malformed(
            N_("После слова Bearer нет токена. Правильно: Authorization: Bearer <токен>.")
        )
    if value[0] in "\"'" or " " in value:
        raise malformed(
            N_("Токен пишут после Bearer через один пробел, без кавычек и лишних слов.")
        )
    t = check_token(at.find(session, value), at.BEARER)
    return Identity(t.username, t.role, at.BEARER, t.owner, t)


def from_basic(session: Session, request: Request, value: str) -> Identity:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decoded = ""
    username, sep, password = decoded.partition(":")
    if not sep:
        raise malformed(
            N_(
                "После Basic должны идти логин и пароль в base64 (логин:пароль). Проще всего — вкладка Authorization → Basic Auth."  # noqa: E501
            )
        )
    user = find_student(session, request)
    if username != at.USERNAME or not at.password_ok(user, password):
        raise unauthorized("invalid_credentials", N_("Неверный логин или пароль."))
    return Identity(at.USERNAME, at.ROLE, "basic", user.student_code if user else None)


def from_authorization(session: Session, request: Request, header: str) -> Identity:
    scheme, _, rest = header.strip().partition(" ")
    rest = rest.strip()
    s = scheme.lower()
    if s == "bearer":
        return from_bearer(session, rest)
    if s == "basic":
        return from_basic(session, request, rest)
    if s.rstrip(":") in ("bearer", "basic"):
        raise malformed(
            N_("Лишнее двоеточие после {scheme}. Правильно: Authorization: Bearer <токен>."),
            {"scheme": scheme.rstrip(":")},
        )
    if s.startswith(tuple(at.PREFIXES.values())) and not rest:
        raise malformed(
            N_("Перед токеном не хватает слова Bearer. Правильно: Authorization: Bearer <токен>.")
        )
    raise malformed(
        N_("Неизвестный способ авторизации «{scheme}». Нужно: Authorization: Bearer <токен>."),
        {"scheme": scheme},
    )


def authenticate(session: Session, request: Request) -> Identity:
    """Кто прислал запрос; ошибка 401 с причиной, если пропуска нет или он не годится."""
    header = request.headers.get("authorization")
    if header is not None:
        return from_authorization(session, request, header)
    key = request.headers.get("x-api-key")
    if key is not None:
        t = check_token(at.find(session, key.strip()), at.API_KEY)
        return Identity(t.username, t.role, at.API_KEY, t.owner, t)
    in_query = [k for k in request.query_params if k.lower() in QUERY_SECRETS]
    if in_query:
        raise unauthorized(
            "missing_credentials",
            N_(
                "Токен или ключ передан в адресе (параметр {param}). Передайте его в заголовке: Authorization: Bearer <токен> или X-API-Key: <ключ> — адрес запроса попадает в логи."  # noqa: E501
            ),
            {"param": in_query[0]},
            {"query_param": in_query[0]},
        )
    raise unauthorized(
        "missing_credentials",
        N_(
            "Нужна авторизация: заголовок Authorization: Bearer <токен>. Токен выдаёт POST /api/auth/login."  # noqa: E501
        ),
    )


def student_or_400(session: Session, request: Request) -> User:
    user = find_student(session, request)
    if user is None:
        raise ApiError(
            400,
            "student_required",
            "Нужен заголовок X-Student-Id с вашим личным кодом (он есть на сайте).",
        )
    return user


def require_fields(data: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [f for f in fields if not isinstance(data.get(f), str) or not data[f]]
    if missing:
        raise ApiError(
            422,
            "validation_error",
            "Не хватает обязательных полей: {fields}",
            {"missing": missing, "invalid": {}},
            params={"fields": ", ".join(missing)},
        )


def invalid_field(field: str, rule: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        "Некоторые поля заполнены неверно.",
        {"missing": [], "invalid": {field: rule}},
    )


@router.post("/auth/login")
async def login(request: Request, session: SessionDep) -> dict[str, Any]:
    data = await parse_json_body(request)
    require_fields(data, ("username", "password"))
    ttl = data.get("expires_in", at.DEFAULT_TTL)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not at.MIN_TTL <= ttl <= at.MAX_TTL:
        raise invalid_field("expires_in", N_("целое число секунд от 5 до 3600"))
    user = find_student(session, request)
    if data["username"] != at.USERNAME or not at.password_ok(user, data["password"]):
        raise ApiError(401, "invalid_credentials", "Неверный логин или пароль.")
    t = at.issue(session, user.student_code if user else None, at.BEARER, ttl)
    return {
        "access_token": t.token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "expires_at": at.iso(t.expires_at),
        "username": t.username,
        "role": t.role,
    }


@router.get("/auth/me")
def me(request: Request, session: SessionDep) -> dict[str, Any]:
    who = authenticate(session, request)
    return {
        "username": who.username,
        "role": who.role,
        "auth": who.auth,
        "expires_at": at.iso(who.token.expires_at) if who.token else None,
    }


@router.post("/auth/api-keys", status_code=201)
def create_api_key(request: Request, session: SessionDep) -> dict[str, Any]:
    who = authenticate(session, request)
    t = at.issue(session, who.owner, at.API_KEY)
    return {"api_key": t.token, "created_at": at.iso(t.created_at), "header": "X-API-Key"}


@router.post("/auth/change-password")
async def change_password(request: Request, session: SessionDep) -> dict[str, Any]:
    who = authenticate(session, request)
    user = student_or_400(session, request)  # в песочнице пароль общий, менять нельзя
    if user.student_code != who.owner:
        raise ApiError(
            403,
            "foreign_account",
            "Токен выдан другому ученику: X-Student-Id и токен должны быть от одной учётки.",
        )
    data = await parse_json_body(request)
    require_fields(data, ("old_password", "new_password"))
    if not at.password_ok(user, data["old_password"]):
        raise ApiError(400, "invalid_old_password", "Старый пароль указан неверно.")
    new = data["new_password"]
    if not 6 <= len(new) <= 64 or new == data["old_password"]:
        raise invalid_field("new_password", N_("от 6 до 64 символов, не совпадает со старым"))
    revoked = at.change_password(session, user, new)
    return {
        "changed": True,
        "revoked": revoked,
        "message": translate(
            N_("Пароль изменён. Все старые токены и ключи отозваны — войдите заново."),
            get_lang(request),
        ),
    }


@router.post("/auth/reset")
def reset(request: Request, session: SessionDep) -> dict[str, Any]:
    """Вернуть пароль support123 и отозвать все токены и ключи (нужен X-Student-Id)."""
    user = student_or_400(session, request)
    revoked = at.reset(session, user)
    return {"reset": True, "username": at.USERNAME, "revoked": revoked}


@router.get("/admin/users")
def admin_users(request: Request, session: SessionDep) -> dict[str, Any]:
    who = authenticate(session, request)
    if who.role != at.ADMIN_ROLE:
        raise ApiError(
            403,
            "insufficient_role",
            "Недостаточно прав: нужна роль {required}, у вас — {role}. Войти заново не поможет: доступ выдаёт администратор.",  # noqa: E501
            {"required_role": at.ADMIN_ROLE, "your_role": who.role},
            params={"required": at.ADMIN_ROLE, "role": who.role},
        )
    return {"items": list(STAFF)}
