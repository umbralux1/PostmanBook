import json
import re

import pytest
from httpx import AsyncClient

from app.i18n import LOCALES_DIR, normalize_lang, translate
from app.i18n_extract import extract, missing

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
EN = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))


def test_every_ui_string_has_english_translation() -> None:
    assert missing("en") == []


def test_catalog_has_no_stale_keys() -> None:
    assert sorted(set(EN) - extract()) == []


def test_translations_keep_placeholders_and_are_english() -> None:
    for ru, en in EN.items():
        assert set(re.findall(r"\{(\w+)\}", ru)) == set(re.findall(r"\{(\w+)\}", en)), ru
        assert not CYRILLIC.search(en), en


def test_translate_with_params_and_fallback() -> None:
    assert translate("Глава {n}", "en", n=3) == "Chapter 3"
    assert translate("Глава {n}", "ru", n=3) == "Глава 3"
    assert translate("Нет такой строки", "en") == "Нет такой строки"
    assert translate("Тело должно быть JSON-объектом {…}.", "en").endswith("{…}.")


def test_normalize_lang() -> None:
    assert normalize_lang("EN") == "en"
    assert normalize_lang("xx") is None


async def test_default_is_english(postman: AsyncClient) -> None:
    r = await postman.get("/chapters/ch01")
    assert '<html lang="en">' in r.text
    assert "All chapters" in r.text
    assert "Your first request: HTTP, URLs and the mini-Postman" in r.text
    # В <head> — каталог переводов с русскими ключами, а t('…') в Alpine-выражениях
    # переводится в браузере. Всё остальное в <body> должно быть английским.
    body = re.sub(r"\bt\('[^']*'", "", r.text.split("<body", 1)[1])
    assert CYRILLIC.findall(body) == []


async def test_switch_to_russian(postman: AsyncClient) -> None:
    r = await postman.get("/lang/ru", params={"next": "/chapters/ch01"})
    assert r.status_code == 303
    assert r.headers["location"] == "/chapters/ch01"
    assert "lang=ru" in r.headers["set-cookie"]
    postman.cookies.set("lang", "ru")
    r = await postman.get("/chapters/ch01")
    assert '<html lang="ru">' in r.text
    assert "Все главы" in r.text
    assert "Первый запрос: HTTP" in r.text
    assert "Первый GET-запрос" in r.text


async def test_english_content(postman: AsyncClient) -> None:
    postman.cookies.set("lang", "en")
    r = await postman.get("/chapters/ch01")
    assert '<html lang="en">' in r.text
    assert "All chapters" in r.text
    assert "Your first request: HTTP, URLs and the mini-Postman" in r.text
    assert "Your first GET request" in r.text
    assert "Check yourself" in r.text
    # Ожидания к ответу и подсказки — английские (в data-атрибуте для JS).
    assert "This is reading data" in r.text.replace("&#39;", "'")
    assert "Чек-лист" not in r.text


async def test_browser_language_does_not_switch_site(postman: AsyncClient) -> None:
    r = await postman.get("/", headers={"Accept-Language": "ru-RU,ru;q=0.9"})
    assert "Learn to diagnose API problems" in r.text


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "evil", None])
async def test_lang_switch_has_no_open_redirect(postman: AsyncClient, target: str | None) -> None:
    params = {"next": target} if target else {}
    r = await postman.get("/lang/en", params=params)
    assert r.headers["location"] == "/"


async def test_unknown_language_falls_back_to_english(postman: AsyncClient) -> None:
    r = await postman.get("/lang/xx")
    assert "lang=en" in r.headers["set-cookie"]


async def test_api_errors_are_translated(postman: AsyncClient) -> None:
    r = await postman.get("/api/status/418", cookies={"lang": "en"})
    assert r.json()["message"] == "This status code is not supported by the trainer."
    r = await postman.get("/api/tickets/999", cookies={"lang": "en"})
    assert r.json()["message"] == "Ticket 999 not found."
    r = await postman.post("/api/tickets", json={"title": ""}, cookies={"lang": "en"})
    body = r.json()
    assert body["message"] == "Required fields are missing: priority"
    assert body["details"]["invalid"]["title"] == "a string of 1..200 characters"
    r = await postman.post(
        "/api/echo",
        content="{bad",
        headers={"Content-Type": "application/json"},
        cookies={"lang": "en"},
    )
    assert r.json()["message"].startswith("The request body is not valid JSON")
    # Коды ошибок не переводятся — по ним работают программы.
    assert r.json()["error"] == "invalid_json"


async def test_api_errors_english_by_default(postman: AsyncClient) -> None:
    r = await postman.get("/api/tickets/999")
    assert r.json()["message"] == "Ticket 999 not found."


async def test_api_errors_in_russian_when_chosen(postman: AsyncClient) -> None:
    r = await postman.get("/api/tickets/999", cookies={"lang": "ru"})
    assert r.json()["message"] == "Заявка 999 не найдена."


async def test_quiz_result_in_english(client: AsyncClient) -> None:
    client.cookies.set("lang", "en")
    r = await client.post(
        "/chapters/ch02/quiz", data={"q1": "A", "q2": "C", "q3": "D", "q4": "B", "q5": "B"}
    )
    assert "Correct answers: 4 of 5" in r.text
    assert "Whether the URL and parameters are correct" in r.text
    assert not CYRILLIC.search(r.text)


async def test_progress_badge_in_english(client: AsyncClient) -> None:
    client.cookies.set("lang", "en")
    r = await client.get("/partials/progress/ch01")
    assert "0 / 5 tasks" in r.text


async def test_task_texts_show_full_site_url(postman: AsyncClient) -> None:
    r = await postman.get("/chapters/ch01")
    html = r.text
    assert "{{BASE_URL}}" not in html
    assert "http://testserver/api/echo?source=postman&amp;user=student" in html
    assert "http://testserver/api/status/404" in html
    # Подсказки проверки (в ожиданиях задания) — тоже с полным адресом.
    assert "http://testserver/api/echo." in html
    # Проверка пути в ответе echo остаётся путём: сервер возвращает path без хоста.
    assert "&#34;equals&#34;: &#34;/api/echo&#34;" in html
    postman.cookies.set("lang", "en")
    r = await postman.get("/chapters/ch01")
    assert "{{BASE_URL}}" not in r.text
    assert "http://testserver/api/echo" in r.text
