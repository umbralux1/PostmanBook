# HTTP-тренажёр

Веб-тренажёр для специалистов поддержки: учимся делать HTTP-запросы, читать
статус-коды, заголовки и тело, а потом переносим навыки в настоящий Postman.
Это безопасная песочница: без реальных токенов и без production.

**Этап 1 (готово):** фаза 1, то есть встроенный мини-Postman, учебный API, автоматическая
проверка заданий, прогресс, чек-лист и тест главы.
**Задел:** модели и API для фазы 2 (`X-Task-Code`, `/last`, SSE) и фазы 3
(вставка ответа внешнего API) уже работают и покрыты тестами. Для них остаётся сделать UI и контент.

## Быстрый старт

### Docker (рекомендуется)

```bash
cp .env.example .env        # необязательно
docker compose up --build
```

Откройте http://localhost:8000. Поднимутся PostgreSQL и приложение. Миграции
(Alembic) применяются при старте контейнера, контент загружается из YAML.

### Локально (SQLite)

Нужен Python 3.11+.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

По умолчанию создаётся `trainer.db` (SQLite). Миграции Alembic применяются при старте
автоматически, в том числе к старой базе, созданной до появления миграций.

### Проверки качества

```bash
pytest                 # тесты (in-memory SQLite, без моков)
node --test tests/js/*.test.cjs   # unit-тесты проверки ответов (нужен Node.js 18+)
ruff check . && ruff format --check .
mypy app               # strict
pre-commit install     # хуки: ruff, mypy, проверка YAML-контента
python -m app.cli check-content
```

## Как это устроено

```
app/
  main.py            FastAPI, CORS, middleware (cookie-сессия + JSON-логи)
  config.py          настройки (переменные TRAINER_*)
  models/            SQLModel: User, Chapter, Task, Attempt, ReceivedRequest, Ticket
  api/               echo.py, tickets.py, tasks.py, progress.py, external_check.py
  services/
    validator.py     фаза 2: сравнение запроса из Postman с эталоном
    hints.py         подсказки для фазы 2 с подстановкой {{param}} (без eval)
    recorder.py      запись ReceivedRequest по X-Task-Code
    external_check.py разбор вставленного ответа (фаза 3)
    task_loader.py   YAML → Pydantic → БД
    sse.py           брокер событий для SSE
  pages.py           HTML-страницы (Jinja2 + HTMX + Alpine.js)
  content/           главы и задания (YAML/Markdown)
  templates/, static/
  static/js/checker.js  фаза 1: проверка задания по ответу сервера (чистые функции)
```

**Как проверяется задание в мини-Postman.** Задание считается выполненным, когда
сервер вернул правильный **ответ**. Учебный API детерминирован: echo возвращает
ровно то, что получил, `/api/status/404` всегда отвечает 404. Поэтому правильный
запрос всегда даёт один и тот же ответ, а неправильный — другой.

Ожидания к ответу описаны в YAML задания. После каждого Send функция
`static/js/checker.js` сверяет с ними ответ и показывает подсказку у первого
несовпадения. Это чистые функции без DOM и сети, они покрыты unit-тестами
(`make test-js`). Когда задание выполнено, фронт вызывает
`POST /api/tasks/{id}/complete`, и сервер сохраняет прогресс.

`tests/test_content_solutions.py` проверяет сам контент: отправляет на настоящий
сервер эталонное решение и типичные ошибки для каждого задания и прогоняет ответы
через тот же `checker.js`. Решение должно засчитываться, ошибки — нет, с нужной
подсказкой. Добавили задание — добавьте туда его решение.

Мини-Postman добавляет к запросам заголовок `X-Task-Code` (в Headers он с замком).
Для фазы 1 сервер его только логирует, он нужен для фазы 2.

**Фаза 2.** Запрос из Postman без cookie, но с `X-Task-Code`, попадает в
`received_requests` с проверкой и рассылается подписчикам
`/api/tasks/{code}/stream`. Страница ожидания: `/tasks/{id}/phase2`.

### Учебный API

| Метод и путь | Что делает |
|---|---|
| `GET/POST/PUT/PATCH/DELETE /api/echo` | Возвращает `method`, `path`, `args`, `headers`, `json`, `data`, `task_code`. Если JSON невалиден (при `Content-Type: application/json`), отвечает `400 invalid_json` |
| `GET /api/status/{code}` | Отвечает этим кодом. Разрешены только 200, 201, 204, 301, 302, 400, 401, 403, 404, 409, 422, 429, 500, 502, 503 |
| `GET/POST /api/tickets`, `GET/PUT/PATCH/DELETE /api/tickets/{id}` | CRUD заявок. Возможные ошибки: 415, 400, 422, 404 |
| `GET /api/tasks/{code}/last` | Последний запрос с этим `X-Task-Code` |
| `GET /api/tasks/{code}/stream` | SSE-поток, событие `request` |
| `POST /api/tasks/{code}/complete` | Фаза 1: фронт сообщает, что задание выполнено (сохраняет прогресс) |
| `POST /api/tasks/{code}/external` | Фаза 3: `{"raw": "<ответ из Postman>"}` |
| `GET /api/progress` | `{chapter_id: {task_id: passed}}` |

Все ошибки возвращаются в одном формате: `{"error": "code", "message": "...", "details": {...}}`.
Интерактивная документация: `/docs`.

Заголовки `Authorization` и `Cookie` в ответе echo и в БД заменяются на `***скрыто***`.

## Как добавить главу

Создайте `app/content/chapters/ch02.yaml`:

```yaml
id: ch02
title: "Авторизация и токены"
order: 2
phase: 1                  # 1 — эмулятор, 2 — свой Postman → учебный API, 3 — внешние API
estimated_minutes: 60
goal: |
  Зачем эта глава.
after_completion: |
  Что человек будет уметь.
checklist:
  - "Пункт чек-листа"
quiz:
  - id: q1
    question: "Текст вопроса (можно с `кодом`)"
    options: {A: "…", B: "…", C: "…", D: "…"}
    answer: B
    explanation: "Почему так."
content_md: |
  ## 2.1. Заголовок раздела
  Обычный Markdown: таблицы, блоки кода, цитаты.
```

Контент загружается в БД при старте приложения. `make dev` перезапускается сам при
правке любых `.yaml`, `.json` и `.py` в `app/`. Если приложение запущено иначе,
выполните `make content-sync` (`python -m app.cli sync-content`): команда проверит
YAML и обновит главы и задания в базе без перезапуска, останется обновить страницу.

## Как добавить задание

Файл `app/content/tasks/ch02.yaml`, где `chapter_id` — id главы:

```yaml
chapter_id: ch02
tasks:
  - id: ch02-task1          # уникальный
    order: 1
    title: "Название"
    description_md: |
      Условие в Markdown.
    expected:               # каким должен быть ответ сервера
      response:
        - {path: status, equals: 200, hint: "Проверь адрес: /api/echo"}
        - {path: body.method, equals: POST, hint: "Нужен POST"}
        - {path: body.args.source, equals: postman, hint: "Добавь ?source=postman"}
        - {path: body.headers.content-type, contains: application/json, hint: "Нужен Content-Type"}
        - {path: body.json.title, exists: true, hint: "В теле нет title"}
        - {path: body.json.priority, in: [low, medium, high], hint: "priority — low/medium/high"}
```

**Утверждения.** `path` начинается с `status`, `headers` (заголовки ответа) или `body`;
дальше ключи через точку. Ответ echo выглядит так: `body.method`, `body.path`,
`body.args.*`, `body.headers.*` (названия в нижнем регистре), `body.json.*`, `body.data`.
У каждого утверждения ровно один оператор:

- `equals` — строгое равенство: `"123"` ≠ `123`;
- `contains` — подстрока или элемент списка;
- `exists: true|false` — `null` считается отсутствием;
- `in: [...]` — одно из значений.

`hint` показывается, если это утверждение — первое несовпавшее. Если `hint` не задан, подсказка формируется автоматически.
Порядок утверждений важен: сначала общее (статус, метод), потом детали.

**Несколько ответов:**

- `steps: [[...], [...]]` — каждый шаг — список утверждений. Без `ordered` шаги можно выполнить в любом порядке (например, «получи 200, 404 и 500»).
- `ordered: true` — шаги строго по порядку (например, «сначала получи 400, потом исправь и получи 200»).
- `require_console: true` + `console_hint` — после правильного ответа нужно открыть вкладку Console.

**Фаза 2** (запросы из своего Postman) проверяется на сервере, и для неё `expected` описывает
**запрос**: `method`, `path` (можно `/api/status/{{code}}`), `query`, `headers`,
`body.json_schema`, а `hints` — тексты подсказок с подстановкой `{{param}}`.

После правки проверьте контент: `python -m app.cli check-content`.

## Языки (русский и английский)

Язык по умолчанию — русский. Английский включается переключателем RU / EN в шапке
и запоминается в cookie `lang`. Язык браузера сайт не учитывает намеренно. От языка
зависят интерфейс, контент глав, подсказки проверки и тексты ошибок API в поле
`message`. Коды ошибок (`error`) не переводятся: на них опираются программы.

**Перевод контента** лежит рядом с оригиналом, с суффиксом языка:

```
app/content/chapters/ch01.yaml      ← оригинал (русский)
app/content/chapters/ch01.en.yaml   ← перевод
app/content/tasks/ch01.yaml
app/content/tasks/ch01.en.yaml
```

Перевод — полный файл того же формата. Загрузчик проверяет, что он совпадает с
оригиналом во всём, что влияет на прохождение: те же `order`, `phase`, id и порядок
заданий, тот же `expected` (отличаются только тексты `hint` и `console_hint`), те же
вопросы теста с теми же вариантами и ответами и столько же пунктов чек-листа.
Поменяли проверку в оригинале — поменяйте её и в переводе, иначе
`python -m app.cli check-content` и запуск приложения сообщат об ошибке. Если
перевода главы нет, на английском она показывается в оригинале.

**Строки интерфейса.** В шаблонах, JS и Python строки пишутся по-русски и служат ключами
каталога `app/locales/en.json`:

- шаблоны — `{{ _("Текст") }}` или `{{ _("Глава {n}", n=chapter.order) }}`;
- JS и Alpine-выражения — `t("Текст")`;
- Python — `ApiError(..., "Текст {id}", params={"id": ...})` или `N_("Текст")`.

Какие строки ещё не переведены, показывает `make i18n-missing`
(`python -m app.i18n_extract --missing en`). Тест `tests/test_i18n.py` падает, если в
каталоге не хватает перевода, если в нём остался неиспользуемый ключ или если в
переводе потерялся `{параметр}`.

**Новый язык** (например, `de`): добавьте код в `LANGUAGES` в `app/i18n.py`, создайте
`app/locales/de.json` и файлы `*.de.yaml`.

## Развёртывание на VPS

1. Установите Docker и плагин compose (Ubuntu: `curl -fsSL https://get.docker.com | sh`).
2. Склонируйте репозиторий и создайте `.env`:
   ```
   POSTGRES_PASSWORD=<длинный случайный пароль>
   TRAINER_PUBLIC_BASE_URL=https://trainer.example.com
   TRAINER_CORS_ORIGINS=["https://trainer.example.com","*"]
   TRAINER_COOKIE_SECURE=true
   ```
3. `docker compose up -d --build`.
4. Поставьте перед приложением nginx или Caddy с HTTPS. Пример для Caddy:
   ```
   trainer.example.com {
       reverse_proxy 127.0.0.1:8000 {
           flush_interval -1     # нужно для SSE
       }
   }
   ```
   В `docker-compose.yml` замените `"8000:8000"` на `"127.0.0.1:8000:8000"`, чтобы приложение
   было доступно только через прокси.
5. Обновление: `git pull && docker compose up -d --build`. Миграции применятся сами.

**Что важно знать:**

- Rate limit (60/мин на IP) и SSE-брокер хранят состояние в памяти процесса. Запускайте
  один воркер uvicorn. Если понадобится масштабирование, перенесите их в Redis.
- После изменения моделей создайте миграцию:
  `alembic revision --autogenerate -m "..."`.

## Фронтенд

Используются Jinja2, HTMX и Alpine.js. Сборки JS нет: библиотеки лежат в `app/static/js/vendor/`.
Tailwind заранее собран в `app/static/css/tailwind.css`. Если вы добавили в шаблоны новые классы, пересоберите CSS:

```bash
npx tailwindcss@3 -i app/static/css/tailwind.src.css -o app/static/css/tailwind.css --minify
```
