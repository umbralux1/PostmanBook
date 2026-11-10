// Кнопка «Reset database» в шапке страницы главы: начать главу заново (только для себя).
// Сервер удаляет прогресс главы (в фазе 2 — ещё тикеты и учётку /api/auth); здесь —
// чек-лист главы (localStorage) и перезагрузка, чтобы карточки нарисовались заново.
(function () {
  window.resetDatabase = function (button, chapterId) {
    if (!window.confirm(t("Начать главу заново? Прогресс по заданиям и тесту этой главы обнулится."))) return;
    if (button) button.disabled = true;
    fetch("/api/progress/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapter_id: chapterId }),
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        try { localStorage.removeItem("checklist-" + chapterId); } catch (e) { /* недоступно */ }
        window.location.reload();
      })
      .catch(function () {
        if (button) button.disabled = false;
        window.alert(t("Не получилось, попробуй ещё раз."));
      });
  };
})();
