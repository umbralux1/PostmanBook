# HTTP-тренажёр — команды для разработки и запуска.
# Начало работы:  make install && make dev
# Список команд:  make help

# Интерпретатор для создания окружения (нужен Python 3.11+).
# Переопределить: make install PYTHON=python3.13
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11; do command -v $$p >/dev/null 2>&1 && { echo $$p; break; }; done)
VENV   ?= .venv
BIN    := $(VENV)/bin
HOST   ?= 127.0.0.1
PORT   ?= 8000
MSG    ?= changes

.DEFAULT_GOAL := help
.PHONY: help install env dev run test test-js cov lint format typecheck check content-check content-sync reset-progress i18n-missing \
        migrate migration css up up-d down logs docker-build docker-clean clean

help: ## Показать список команд
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- Окружение ----------

$(BIN)/activate:
	@test -n "$(PYTHON)" || { echo "Не найден Python 3.11+. Установите его или укажите: make install PYTHON=/путь/к/python3.12"; exit 1; }
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Нужен Python 3.11+, а $(PYTHON) старше"; exit 1; }
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: $(BIN)/activate env ## Создать .venv и установить зависимости (с dev)
	$(BIN)/pip install -e ".[dev]"
	@echo "Готово. Запуск: make dev"

env: ## Создать .env из .env.example (если его ещё нет)
	@test -f .env || { cp .env.example .env && echo "Создан .env"; }

# ---------- Запуск ----------

dev: ## Запустить с автоперезагрузкой (код и YAML/JSON контента) → http://127.0.0.1:8000
	$(BIN)/uvicorn app.main:app --reload --reload-dir app \
		--reload-include '*.yaml' --reload-include '*.json' --host $(HOST) --port $(PORT)

run: ## Запустить с автоперезагрузкой кода (без слежения за YAML/JSON — для этого make dev)
	$(BIN)/uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

# ---------- Качество ----------

test: ## Запустить Python-тесты (включая прогон контента через checker.js)
	$(BIN)/pytest -q

test-js: ## Unit-тесты JS (static/js/checker.js, task_order.js), нужен Node.js 18+
	node --test tests/js/*.test.cjs

lint: ## Проверить код ruff
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Отформатировать код и исправить то, что ruff исправляет сам
	$(BIN)/ruff check . --fix
	$(BIN)/ruff format .

typecheck: ## mypy --strict
	$(BIN)/mypy app

content-check: ## Проверить YAML глав и заданий
	$(BIN)/python -m app.cli check-content

content-sync: ## Обновить главы и задания в БД из YAML (без перезапуска сервера)
	$(BIN)/python -m app.cli sync-content

i18n-missing: ## Показать строки интерфейса без английского перевода
	$(BIN)/python -m app.i18n_extract --missing en

check: lint typecheck content-check test test-js ## Все проверки перед коммитом

# ---------- База данных ----------

migrate: ## Применить миграции Alembic
	$(BIN)/alembic upgrade head

migration: ## Создать миграцию: make migration MSG="add field"
	$(BIN)/alembic revision --autogenerate -m "$(MSG)"

# ---------- Фронтенд ----------

css: ## Пересобрать Tailwind CSS (нужен Node.js)
	npx --yes tailwindcss@3 -i app/static/css/tailwind.src.css -o app/static/css/tailwind.css --minify

# ---------- Docker ----------

up: env ## docker compose up (приложение + SQLite в томе) → http://localhost:8000
	docker compose up --build

up-d: env ## То же, в фоне
	docker compose up --build -d

down: ## Остановить контейнеры
	docker compose down

logs: ## Логи приложения в Docker
	docker compose logs -f app

docker-clean: ## Остановить контейнеры и удалить данные БД (volume)
	docker compose down -v

# ---------- Уборка ----------

clean: ## Удалить кэши и локальную SQLite-базу
	find . -name __pycache__ -type d -prune -not -path "./$(VENV)/*" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache *.egg-info trainer.db


reset-progress: ## Сбросить прогресс ВСЕХ пользователей (спросит подтверждение; без вопроса: YES=1)
	$(BIN)/python -m app.cli reset-progress $(if $(YES),--yes)
