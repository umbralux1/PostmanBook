# Исходники контента

Здесь авторы держат черновики глав (Markdown, заметки, скриншоты Postman),
пока они не готовы к публикации. Сайт читает только `app/content/`.

План курса — какие главы, в каком порядке, что нужно от учебного API — в
[`COURSE_PLAN.md`](COURSE_PLAN.md).

Когда глава готова:

1. Перенесите текст в `app/content/chapters/chNN.yaml` (поле `content_md`).
2. Опишите задания в `app/content/tasks/chNN.yaml`.
3. Проверьте: `python -m app.cli check-content`.
