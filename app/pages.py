"""HTML-страницы (Jinja2 + HTMX)."""

import re
from typing import Any

import markdown as md
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session

from app.api.rooms import room_info
from app.config import BASE_DIR, get_settings
from app.dependencies import RequiredUserDep, SessionDep
from app.errors import ApiError
from app.i18n import (
    DEFAULT_LANG,
    LANG_COOKIE,
    LANGUAGES,
    catalog,
    get_lang,
    normalize_lang,
    translate,
)
from app.models import Attempt, Chapter, Task, User
from app.services.localize import chapter_view, task_view
from app.services.progress import passed_task_ids, quiz_task_id
from app.services.task_loader import list_chapters, list_tasks

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")


def _separate_lists(text: str) -> str:
    """Вставить пустую строку перед списком, идущим сразу за абзацем.

    Python-Markdown (в отличие от GitHub) без неё склеивает список с абзацем,
    а авторы контента часто её не ставят.
    """
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        elif not in_code and _LIST_ITEM.match(line) and out:
            prev = out[-1]
            if prev.strip() and not _LIST_ITEM.match(prev) and not prev.startswith((" ", "\t")):
                out.append("")
        out.append(line)
    return "\n".join(out)


def render_md(text: str) -> Markup:
    # Контент курса — доверенный (лежит в репозитории), поэтому Markup допустим.
    html = md.markdown(
        _separate_lists(text or ""),
        extensions=["tables", "fenced_code", "sane_lists", "md_in_html"],
    )
    return Markup(html)


def task_kind(expected: dict[str, Any]) -> str:
    """Тип задания фазы 1 — для пояснений в карточке."""
    if expected.get("steps"):
        return "ordered" if expected.get("ordered") else "sequence"
    if expected.get("require_console"):
        return "console"
    return "single"


def render_md_inline(text: str) -> Markup:
    """Markdown без обёртки <p> — для коротких строк (варианты ответа, вопросы)."""
    html = md.markdown(text or "")
    if html.startswith("<p>") and html.endswith("</p>"):
        html = html[3:-4]
    return Markup(html)


templates.env.filters["md"] = render_md
templates.env.filters["mdi"] = render_md_inline
templates.env.globals["settings"] = get_settings()
templates.env.globals["task_kind"] = task_kind

router = APIRouter(include_in_schema=False)


def render(
    request: Request,
    name: str,
    context: dict[str, Any],
    session: Session | None = None,
    user: User | None = None,
) -> HTMLResponse:
    """TemplateResponse + язык (lang, _(), каталог для JS) + комната пользователя."""
    lang = get_lang(request)

    def _(text: str, **params: Any) -> str:
        return translate(text, lang, **params)

    ctx = {
        "lang": lang,
        "_": _,
        "languages": LANGUAGES,
        "js_catalog": catalog(lang),
        "room": room_info(session, user) if session is not None and user is not None else None,
        **context,
    }
    return templates.TemplateResponse(request, name, ctx)


def site_url(request: Request) -> str:
    """Адрес сайта, с которого открыта страница: http://localhost:8000, https://… ."""
    return str(request.base_url).rstrip("/")


def _safe_next(url: str | None) -> str:
    """Только относительный путь на этом сайте (без open redirect)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"


@router.get("/lang/{code}")
def set_language(code: str, next: str | None = None) -> RedirectResponse:
    lang = normalize_lang(code) or DEFAULT_LANG
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        LANG_COOKIE,
        lang,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )
    return response


def _get_chapter(session: SessionDep, chapter_id: str) -> Chapter:
    ch = session.get(Chapter, chapter_id)
    if ch is None:
        raise ApiError(404, "not_found", "Глава не найдена")
    return ch


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: SessionDep, user: RequiredUserDep) -> HTMLResponse:
    lang = get_lang(request)
    passed = passed_task_ids(session, user)
    chapters: list[dict[str, Any]] = []
    for ch in list_chapters(session):
        tasks = list_tasks(session, ch.id)
        done = sum(1 for t in tasks if t.id in passed)
        chapters.append(
            {
                "chapter": chapter_view(ch, lang, site_url(request)),
                "total": len(tasks),
                "done": done,
                "quiz_passed": quiz_task_id(ch.id) in passed,
            }
        )
    return render(request, "index.html", {"chapters": chapters}, session, user)


@router.get("/chapters/{chapter_id}", response_class=HTMLResponse)
def chapter_page(
    chapter_id: str, request: Request, session: SessionDep, user: RequiredUserDep
) -> HTMLResponse:
    lang = get_lang(request)
    base = site_url(request)
    ch = chapter_view(_get_chapter(session, chapter_id), lang, base)
    tasks = [task_view(t, lang, base) for t in list_tasks(session, ch.id)]
    passed = passed_task_ids(session, user)
    return render(
        request,
        "chapter.html",
        {
            "chapter": ch,
            "tasks": tasks,
            "passed": passed,
            "done": sum(1 for t in tasks if t.id in passed),
            "quiz": ch.meta.get("quiz", []),
            "quiz_passed": quiz_task_id(ch.id) in passed,
            # Для комнаты: по id задания (пришедшему от другого участника) найти его на своём языке.
            "tasks_js": {t.id: {"title": t.title, "expected": t.expected} for t in tasks},
        },
        session,
        user,
    )


@router.get("/partials/progress/{chapter_id}", response_class=HTMLResponse)
def progress_partial(
    chapter_id: str, request: Request, session: SessionDep, user: RequiredUserDep
) -> HTMLResponse:
    tasks = list_tasks(session, chapter_id)
    passed = passed_task_ids(session, user)
    return render(
        request,
        "components/progress_badge.html",
        {
            "done": sum(1 for t in tasks if t.id in passed),
            "total": len(tasks),
            "chapter_id": chapter_id,
        },
    )


@router.post("/chapters/{chapter_id}/quiz", response_class=HTMLResponse)
async def submit_quiz(
    chapter_id: str, request: Request, session: SessionDep, user: RequiredUserDep
) -> HTMLResponse:
    ch = chapter_view(_get_chapter(session, chapter_id), get_lang(request), site_url(request))
    form = await request.form()
    questions: list[dict[str, Any]] = ch.meta.get("quiz", [])
    results: list[dict[str, Any]] = []
    for q in questions:
        given = form.get(q["id"])
        results.append(
            {
                "question": q["question"],
                "given": given if isinstance(given, str) else None,
                "answer": q["answer"],
                "answer_text": q["options"][q["answer"]],
                "ok": given == q["answer"],
                "explanation": q.get("explanation", ""),
            }
        )
    score = sum(r["ok"] for r in results)
    passed = bool(results) and score == len(results)
    session.add(
        Attempt(
            user_id=user.id,
            task_id=quiz_task_id(ch.id),
            passed=passed,
            request_payload={"answers": {q["id"]: form.get(q["id"]) for q in questions}},
            response_payload={"score": score, "total": len(results)},
        )
    )
    session.commit()
    return render(
        request,
        "components/quiz_result.html",
        {"results": results, "score": score, "total": len(results), "passed": passed},
    )


def _task_or_404(session: SessionDep, task_id: str, request: Request) -> Any:
    task = session.get(Task, task_id)
    if task is None:
        raise ApiError(404, "not_found", "Задание не найдено")
    return task_view(task, get_lang(request), site_url(request))


@router.get("/tasks/{task_id}/phase2", response_class=HTMLResponse)
def phase2_page(
    task_id: str, request: Request, session: SessionDep, user: RequiredUserDep
) -> HTMLResponse:
    task = _task_or_404(session, task_id, request)
    return render(request, "phases/phase2_wait.html", {"task": task}, session, user)


@router.get("/tasks/{task_id}/phase3", response_class=HTMLResponse)
def phase3_page(
    task_id: str, request: Request, session: SessionDep, user: RequiredUserDep
) -> HTMLResponse:
    task = _task_or_404(session, task_id, request)
    return render(request, "phases/phase3_paste.html", {"task": task}, session, user)
