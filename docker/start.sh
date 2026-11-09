#!/bin/sh
# Запуск в контейнере: права на папку с базой → миграции → uvicorn.
set -e

# Папка с файлом SQLite (из TRAINER_DATABASE_URL=sqlite:////srv/data/trainer.db).
DB_PATH="${TRAINER_DATABASE_URL#sqlite:///}"
DATA_DIR="$(dirname "$DB_PATH")"

if [ "$(id -u)" = "0" ]; then
  # Тома Docker и диски хостингов монтируются с владельцем root: отдаём папку
  # пользователю trainer и перезапускаем этот же скрипт уже без прав root.
  mkdir -p "$DATA_DIR"
  chown -R trainer:trainer "$DATA_DIR"
  exec python -c '
import os, pwd, sys
u = pwd.getpwnam("trainer")
os.setgroups([]); os.setgid(u.pw_gid); os.setuid(u.pw_uid)
os.environ["HOME"] = u.pw_dir
os.execv(sys.argv[1], sys.argv[1:])
' "$0" "$@"
fi

alembic upgrade head
# PORT задают хостинги (Render — 10000); локально и в docker compose — 8000.
# --forwarded-allow-ips='*': доверять X-Forwarded-Proto от прокси хостинга, иначе за
# HTTPS-прокси приложение решит, что работает на http://, и адреса в заданиях сломаются.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
