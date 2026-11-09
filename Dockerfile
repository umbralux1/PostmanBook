FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # База — файл SQLite в /srv/data. Эту папку монтируют как том (docker compose)
    # или постоянный диск (Render), чтобы данные переживали перезапуск.
    TRAINER_DATABASE_URL=sqlite:////srv/data/trainer.db

WORKDIR /srv

RUN useradd --create-home --uid 1000 trainer

COPY pyproject.toml README.md ./
COPY app ./app
# editable: шаблоны, статика и YAML читаются прямо из /srv/app
RUN pip install -e .

COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh && mkdir -p /srv/data && chown -R trainer:trainer /srv

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'))" || exit 1

# Скрипт стартует от root только чтобы выдать права на папку с базой,
# затем сразу понижает права до пользователя trainer.
CMD ["/usr/local/bin/start.sh"]
