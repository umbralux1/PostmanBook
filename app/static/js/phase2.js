// Фаза 2: панель «Твой Postman» на странице главы — только для чтения.
//
// Запросы ученик отправляет из настоящего Postman с заголовками X-Student-Id
// (личный код) и X-Task-Code (id задания). Сервер пишет их вместе с ответами в журнал
// ученика; страница берёт журнал (GET /api/journal) и новые записи по SSE
// (/api/journal/stream) и проверяет задания тем же checker.js, что и в фазе 1:
// история задания = ответы на запросы с его X-Task-Code (старые → новые).
// Засчитывание личное: POST /api/tasks/{id}/complete только себе.
document.addEventListener("alpine:init", function () {
  var MAX_ENTRIES = 100;
  var RECONNECT_MS = 3000;

  Alpine.data("postmanPanel", function () {
    return {
      studentCode: window.STUDENT_CODE || "",
      baseUrl: window.location.origin,
      entries: [],        // журнал: старые → новые
      opened: null,       // id раскрытой записи
      connection: "connecting", // connecting | live | lost
      validation: null,   // результат checker.js для выбранного задания
      copied: "",
      source: null,

      init: function () {
        var self = this;
        window.addEventListener("task-selected", function () { self.evaluateCurrent(); });
        this.load(true);
      },

      load: async function (initial) {
        try {
          var res = await fetch("/api/journal", { credentials: "same-origin" });
          if (res.ok) {
            var data = await res.json();
            this.merge(data.items || []);
          }
        } catch (e) { /* журнал подтянется при следующем подключении */ }
        this.evaluateAll(initial);
        if (initial) this.connect();
      },

      connect: function () {
        var self = this;
        if (!window.EventSource) { this.connection = "lost"; return; }
        var es = new EventSource("/api/journal/stream");
        this.source = es;
        var wasLost = false;
        es.onopen = function () {
          self.connection = "live";
          // После обрыва подтягиваем то, что пришло, пока связи не было.
          if (wasLost) { wasLost = false; self.load(false); }
        };
        es.addEventListener("request", function (e) {
          var entry;
          try { entry = JSON.parse(e.data); } catch (err) { return; }
          self.add(entry);
        });
        es.onerror = function () {
          self.connection = "lost";
          wasLost = true;
          if (es.readyState === EventSource.CLOSED) {
            setTimeout(function () { self.connect(); }, RECONNECT_MS);
          }
        };
      },

      merge: function (items) {
        var known = {};
        this.entries.forEach(function (e) { known[e.id] = true; });
        var added = items.filter(function (e) { return !known[e.id]; });
        if (!added.length) return;
        var all = this.entries.concat(added);
        all.sort(function (a, b) { return a.received_at < b.received_at ? -1 : a.received_at > b.received_at ? 1 : 0; });
        this.entries = all.slice(-MAX_ENTRIES);
      },

      add: function (entry) {
        this.merge([entry]);
        this.opened = entry.id;
        if (entry.task_code) this.evaluate(entry.task_code, false);
        this.evaluateCurrent();
      },

      // ---------- Проверка заданий (checker.js) ----------
      historyOf: function (taskId) {
        return this.entries
          .filter(function (e) { return e.task_code === taskId; })
          .map(function (e) {
            var r = e.response || {};
            return window.TaskChecker.normalizeResponse(r.status, Object.entries(r.headers || {}), r.body);
          });
      },

      // initial: проверка при открытии страницы — без автоперехода.
      evaluate: function (taskId, initial) {
        var info = (window.TASKS || {})[taskId];
        var store = Alpine.store("task");
        if (!info || store.passed[taskId]) return;
        var history = this.historyOf(taskId);
        if (!history.length) return;
        var v = window.TaskChecker.evaluateTask(info.expected, history, {});
        if (v.passed) this.complete(taskId, history, !initial && store.id === taskId);
      },

      evaluateAll: function (initial) {
        var self = this;
        var store = Alpine.store("task");
        var before = store.id && store.passed[store.id];
        (window.TASK_ORDER || []).forEach(function (id) { self.evaluate(id, initial); });
        // Выбранное задание засчиталось по старым запросам — перейти к первому невыполненному.
        if (initial && store.id && store.passed[store.id] && !before) store.openFirst();
        this.evaluateCurrent();
      },

      evaluateCurrent: function () {
        var store = Alpine.store("task");
        if (!store.id || !store.expected) { this.validation = null; return; }
        var history = this.historyOf(store.id);
        this.validation = history.length
          ? window.TaskChecker.evaluateTask(store.expected, history, {})
          : null;
      },

      complete: async function (taskId, history, advance) {
        var store = Alpine.store("task");
        store.passed[taskId] = true;
        if (advance) store.advanceFrom(taskId);
        try {
          await fetch("/api/tasks/" + encodeURIComponent(taskId) + "/complete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ responses: history.slice(-5) }),
            credentials: "same-origin",
          });
          if (window.htmx) htmx.trigger(document.body, "progress-changed");
        } catch (e) { /* прогресс не сохранился — задание всё равно видно как выполненное */ }
      },

      // ---------- Помощники для шаблона ----------
      newestFirst: function () {
        return this.entries.slice().reverse();
      },
      copy: function (text, key) {
        var self = this;
        if (!text || !navigator.clipboard || !navigator.clipboard.writeText) return;
        navigator.clipboard.writeText(text).then(function () {
          self.copied = key;
          setTimeout(function () { if (self.copied === key) self.copied = ""; }, 2000);
        }, function () {});
      },
      toggle: function (id) {
        this.opened = this.opened === id ? null : id;
      },
      fullPath: function (e) {
        var qs = new URLSearchParams(e.query || {}).toString();
        return e.path + (qs ? "?" + qs : "");
      },
      time: function (e) {
        var d = new Date(e.received_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(e.received_at) ? e.received_at : e.received_at + "Z");
        return isNaN(d) ? "" : d.toLocaleTimeString();
      },
      // Почему запрос не засчитан ни одному заданию.
      entryNote: function (e) {
        if (!e.task_code) return t("Нет заголовка X-Task-Code — запрос не засчитывается ни одному заданию.");
        if (!e.known_task) return t("Задания с кодом {code} нет. Скопируй X-Task-Code с карточки задания.", { code: e.task_code });
        return "";
      },
      taskTitle: function (code) {
        var info = (window.TASKS || {})[code];
        return info ? info.title : "";
      },
      statusClass: function (code) {
        if (code >= 200 && code < 300) return "pm-ok";
        if (code >= 300 && code < 400) return "pm-redirect";
        return "pm-fail";
      },
      methodColor: function (method) {
        var colors = { GET: "#007f31", POST: "#ad7a03", PUT: "#0053b8", PATCH: "#623497", DELETE: "#8e1a10" };
        return colors[method] || "#212121";
      },
      pretty: function (text) {
        if (text == null || text === "") return '<span style="color:#a6a6a6">' + window.escapeHtml(t("(пусто)")) + "</span>";
        try { return window.highlightJson(JSON.parse(text)); } catch (e) { return window.escapeHtml(text); }
      },
      prettyHeaders: function (obj) {
        return window.highlightJson(obj || {});
      },
    };
  });
});
