// Выбранное задание главы (Alpine.store("task")), автопереход и чек-лист главы.
// Общее для обеих фаз: в фазе 1 задание решают в мини-Postman (builder.js),
// в фазе 2 — в настоящем Postman, а страница показывает журнал (phase2.js).
document.addEventListener("alpine:init", function () {
  // Фаза 2: у каждого в комнате свой Postman — выбор задания не рассылается.
  var personal = window.CHAPTER_PHASE === 2;

  // Пауза перед автопереходом: ученик успевает увидеть, что задание засчитано.
  var ADVANCE_DELAY_MS = 2000;
  var advanceTimer = null;

  Alpine.store("task", {
    id: null,
    title: "",
    expected: null,
    passed: {},
    // opts.reveal: раскрыть карточку задания и прокрутить к ней (автопереход).
    select: function (id, title, expected, fromRemote, opts) {
      clearTimeout(advanceTimer);
      this.id = id;
      this.title = title;
      this.expected = expected;
      if (!fromRemote && !personal && window.Collab) window.Collab.local("taskId", id);
      window.dispatchEvent(new CustomEvent("task-selected", { detail: { id: id } }));
      if (opts && opts.reveal) {
        window.dispatchEvent(new CustomEvent("task-reveal", { detail: { id: id } }));
        return;
      }
      var el = document.getElementById("builder") || document.getElementById("postman-panel");
      if (el && window.innerWidth < 1024) el.scrollIntoView({ behavior: "smooth" });
    },
    selectById: function (id, fromRemote, opts) {
      var info = (window.TASKS || {})[id];
      if (info) this.select(id, info.title, info.expected, fromRemote, opts);
    },
    // При открытии главы — первое невыполненное задание. Не рассылается в комнату:
    // если там уже выбрано задание, оно придёт в welcome и заменит это.
    openFirst: function () {
      var id = window.TaskOrder.firstOpen(window.TASK_ORDER || [], this.passed);
      if (id) this.selectById(id, true);
    },
    // Задание засчитано → через паузу следующее невыполненное по порядку.
    // Вызывает только тот, кто засчитал: в фазе 1 выбор разойдётся по комнате как taskId.
    // Если за паузу выбрали другое задание, переход отменяется (select сбрасывает таймер).
    advanceFrom: function (id) {
      var self = this;
      clearTimeout(advanceTimer);
      advanceTimer = setTimeout(function () {
        if (self.id !== id) return;
        var next = window.TaskOrder.nextAfter(window.TASK_ORDER || [], self.passed, id);
        if (next) self.selectById(next, false, { reveal: true });
      }, ADVANCE_DELAY_MS);
    },
  });

  // Чек-лист главы: отметки хранятся только в этом браузере.
  Alpine.data("checklist", function (key) {
    var initial = {};
    try { initial = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { initial = {}; }
    return {
      done: initial,
      save: function () {
        try { localStorage.setItem(key, JSON.stringify(this.done)); } catch (e) { /* недоступно */ }
      },
    };
  });
});
