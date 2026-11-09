FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN useradd --create-home --uid 1000 trainer

COPY pyproject.toml README.md ./
COPY app ./app
# editable: шаблоны, статика и YAML читаются прямо из /srv/app
RUN pip install -e .

COPY alembic.ini ./
COPY alembic ./alembic

# Приложение работает не от root: папка должна быть доступна пользователю trainer
# (иначе SQLite без настроенной базы не сможет создать файл).
RUN chown -R trainer:trainer /srv

USER trainer
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'))" || exit 1

# Миграции → запуск. Контент из YAML синхронизируется при старте приложения.
# PORT задают хостинги (Render — 10000); локально и в docker compose — 8000.
# --forwarded-allow-ips='*': доверять X-Forwarded-Proto от прокси хостинга, иначе
# за HTTPS-прокси приложение решит, что оно на http://, и адреса в заданиях сломаются.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
