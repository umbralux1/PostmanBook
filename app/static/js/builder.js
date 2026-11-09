// Мини-Postman: собирает запрос, отправляет fetch() на учебный API,
// показывает ответ, ведёт журнал (Console) и получает результат проверки задания.
document.addEventListener("alpine:init", function () {
  // Поля мини-Postman, общие для всех в комнате (сервер принимает только их).
  var SHARED_FIELDS = [
    "method", "url", "params", "headers", "bodyMode", "body",
    "tab", "respTab", "openedLog", "sending", "response", "log", "history", "consoleOpenedAt",
  ];
  var DEFAULTS = {
    method: function () { return "GET"; },
    url: function () { return window.location.origin + "/api/echo"; },
    params: function () { return [{ key: "", value: "" }]; },
    headers: function () { return [{ key: "", value: "" }]; },
    bodyMode: function () { return "none"; },
    body: function () { return ""; },
    tab: function () { return "params"; },
    respTab: function () { return "body"; },
    openedLog: function () { return null; },
    sending: function () { return false; },
    response: function () { return null; },
    log: function () { return []; },
    history: function () { return {}; },
    consoleOpenedAt: function () { return {}; },
  };
  var HEADER_NAMES = ["Content-Type", "Accept", "Authorization", "X-Debug-Source", "Cache-Control"];
  var MAX_LOG = 10;

  Alpine.store("task", {
    id: null,
    title: "",
    expected: null,
    passed: {},
    select: function (id, title, expected, fromRemote) {
      this.id = id;
      this.title = title;
      this.expected = expected;
      if (!fromRemote && window.Collab) window.Collab.local("taskId", id);
      window.dispatchEvent(new CustomEvent("task-selected", { detail: { id: id } }));
      var el = document.getElementById("builder");
      if (el && window.innerWidth < 1024) el.scrollIntoView({ behavior: "smooth" });
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

  Alpine.data("builder", function () {
    return {
      methods: ["GET", "POST", "PUT", "PATCH", "DELETE"],
      headerNames: HEADER_NAMES,
      method: "GET",
      url: window.location.origin + "/api/echo",
      params: [],
      headers: [{ key: "", value: "" }],
      bodyMode: "none",
      body: "",
      tab: "params",
      respTab: "body",
      sending: false,
      error: null,
      response: null,
      log: [],
      openedLog: null,
      validation: null,
      bad: {},
      history: {},          // id задания → ответы сервера (старые → новые)
      consoleOpenedAt: {},  // id задания → сколько ответов было, когда открыли Console

      init: function () {
        this.syncParamsFromUrl();
        var self = this;
        window.addEventListener("task-selected", function () {
          self.validation = null;
          self.bad = {};
          self.$nextTick(function () { self.evaluate(true); });
        });
        this.initCollab();
      },

      // ---------- Совместная работа: общий мини-Postman в комнате ----------
      initCollab: function () {
        var C = window.Collab;
        if (!C) return;
        var self = this;
        SHARED_FIELDS.forEach(function (f) {
          self.$watch(f, function (v) { C.local(f, JSON.parse(JSON.stringify(v === undefined ? null : v))); });
        });
        C.onPatch(function (field, value) { self.applyRemote(field, value); });
      },

      applyRemote: function (field, value) {
        if (field === "taskId") {
          var info = (window.TASKS || {})[value];
          var store = Alpine.store("task");
          if (info) store.select(value, info.title, info.expected, true);
          else if (value === null) store.select(null, "", null, true);
          return;
        }
        if (SHARED_FIELDS.indexOf(field) === -1) return;
        // Сохраняем каретку, если пользователь сейчас печатает в поле.
        var active = document.activeElement;
        var hasCaret = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
        var start = hasCaret ? active.selectionStart : null;
        var end = hasCaret ? active.selectionEnd : null;
        this[field] = value === null || value === undefined ? DEFAULTS[field]() : JSON.parse(JSON.stringify(value));
        var self = this;
        this.$nextTick(function () {
          if (hasCaret && document.activeElement === active && start !== null) {
            try {
              active.setSelectionRange(Math.min(start, active.value.length), Math.min(end, active.value.length));
            } catch (e) { /* поле без выделения */ }
          }
          if (field === "history" || field === "consoleOpenedAt") self.evaluate(true);
          if (field === "response" || field === "history") self.bad = self.bad || {};
        });
      },

      // ---------- Params <-> URL ----------
      splitUrl: function () {
        var i = this.url.indexOf("?");
        return i < 0 ? [this.url, ""] : [this.url.slice(0, i), this.url.slice(i + 1)];
      },
      syncParamsFromUrl: function () {
        var qs = this.splitUrl()[1];
        var list = [];
        new URLSearchParams(qs).forEach(function (v, k) {
          list.push({ key: k, value: v });
        });
        list.push({ key: "", value: "" });
        this.params = list;
      },
      syncUrlFromParams: function () {
        var base = this.splitUrl()[0];
        var usp = new URLSearchParams();
        this.params.forEach(function (p) {
          if (p.key.trim()) usp.append(p.key.trim(), p.value);
        });
        var qs = usp.toString();
        this.url = qs ? base + "?" + qs : base;
        var last = this.params[this.params.length - 1];
        if (!last || last.key || last.value) this.params.push({ key: "", value: "" });
      },
      removeParam: function (i) {
        this.params.splice(i, 1);
        this.syncUrlFromParams();
      },

      // ---------- Headers ----------
      onHeaderInput: function () {
        var last = this.headers[this.headers.length - 1];
        if (!last || last.key || last.value) this.headers.push({ key: "", value: "" });
      },
      removeHeader: function (i) {
        this.headers.splice(i, 1);
        if (!this.headers.length) this.headers.push({ key: "", value: "" });
      },
      headerValueOptions: function (key) {
        var k = (key || "").toLowerCase();
        if (k === "content-type" || k === "accept") return ["application/json", "text/plain", "*/*"];
        if (k === "authorization") return ["Bearer test-token-123"];
        return [];
      },
      activeHeaderCount: function () {
        return this.headers.filter(function (h) { return h.key.trim(); }).length;
      },
      activeParamCount: function () {
        return this.params.filter(function (p) { return p.key.trim(); }).length;
      },

      // ---------- Body ----------
      get bodyError() {
        return this.bodyMode === "json" ? window.jsonError(this.body) : null;
      },
      prettify: function () {
        try { this.body = JSON.stringify(JSON.parse(this.body), null, 2); } catch (e) { /* оставляем как есть */ }
      },

      // ---------- Send ----------
      buildHeaders: function () {
        var h = {};
        this.headers.forEach(function (row) {
          if (row.key.trim()) h[row.key.trim()] = row.value;
        });
        var task = Alpine.store("task");
        if (task.id) h["X-Task-Code"] = task.id;
        return h;
      },
      isLocal: function () {
        try {
          return new URL(this.url, window.location.origin).origin === window.location.origin;
        } catch (e) {
          return false;
        }
      },
      send: async function () {
        this.error = null;
        if (!this.url.trim()) { this.error = t("Укажи URL."); return; }
        if (!this.isLocal()) {
          this.error = t("В тренажёре запросы идут только на учебный API этого сайта (например, /api/echo). Внешние адреса — в реальном Postman.");
          return;
        }
        var hasBody = this.bodyMode === "json" && this.method !== "GET";
        if (this.bodyMode === "json" && this.method === "GET" && this.body.trim()) {
          this.error = t("У GET-запроса нет тела. Выбери метод POST или переключи Body на none.");
          return;
        }
        var headers = this.buildHeaders();
        var started = performance.now();
        this.sending = true;
        var entry = {
          at: new Date().toLocaleTimeString(),
          request: {
            method: this.method,
            url: new URL(this.url, window.location.origin).toString(),
            headers: headers,
            body: hasBody ? this.body : null,
          },
          response: null,
        };
        try {
          var res = await fetch(this.url, {
            method: this.method,
            headers: headers,
            body: hasBody ? this.body : undefined,
            credentials: "same-origin",
          });
          var text = await res.text();
          var timeMs = Math.round(performance.now() - started);
          var respHeaders = [];
          res.headers.forEach(function (v, k) { respHeaders.push([k, v]); });
          var json = null;
          try { json = text ? JSON.parse(text) : null; } catch (e) { json = null; }
          this.response = {
            status: res.status,
            statusText: res.statusText || statusText(res.status),
            timeMs: timeMs,
            size: new Blob([text]).size,
            text: text,
            json: json,
            headers: respHeaders,
          };
          entry.response = { status: res.status, headers: respHeaders, body: text };
          this.recordResponse(window.TaskChecker.normalizeResponse(res.status, respHeaders, text));
        } catch (e) {
          this.error = t("Запрос не ушёл: {reason}", { reason: e.message });
          entry.response = { status: 0, headers: [], body: String(e) };
        } finally {
          this.sending = false;
          this.log.unshift(entry);
          if (this.log.length > MAX_LOG) this.log.pop();
          this.openedLog = 0;
        }
      },

      // ---------- Проверка задания по ответу сервера ----------
      recordResponse: function (response) {
        var task = Alpine.store("task");
        if (!task.id || !task.expected) return;
        var list = this.history[task.id] || (this.history[task.id] = []);
        list.push(response);
        if (list.length > 20) list.shift();
        this.evaluate(false);
      },

      // fromRemote = true: изменение пришло от другого участника комнаты.
      // Результат считаем у всех одинаково, а засчитывает задание тот, кто сделал действие.
      evaluate: function (fromRemote) {
        var task = Alpine.store("task");
        var list = this.history[task.id] || [];
        if (!task.id || !task.expected || !list.length) return;
        var opened = this.consoleOpenedAt[task.id];
        var v = window.TaskChecker.evaluateTask(task.expected, list, {
          consoleOpenedAt: opened === undefined ? null : opened,
        });
        this.validation = v;
        var bad = {};
        var self = this;
        v.results.forEach(function (r) { if (!r.ok) bad[self.fieldOf(r.path)] = true; });
        if (v.waitingConsole) bad.console = true;
        this.bad = bad;
        if (v.passed && !task.passed[task.id] && !fromRemote) this.complete(task.id, list);
      },

      // Какую часть мини-Postman подсветить по пути в ответе.
      fieldOf: function (path) {
        if (path === "body.method") return "method";
        if (path === "status" || path === "body.path" || path === "body.status") return "url";
        if (path.indexOf("body.args") === 0) return "params";
        if (path.indexOf("body.headers") === 0 || path.indexOf("headers") === 0) return "headers";
        return "body";
      },

      complete: async function (taskId, list) {
        var task = Alpine.store("task");
        task.passed[taskId] = true;
        try {
          await fetch("/api/tasks/" + encodeURIComponent(taskId) + "/complete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ responses: list.slice(-5) }),
            credentials: "same-origin",
          });
          if (window.htmx) htmx.trigger(document.body, "progress-changed");
        } catch (e) { /* прогресс не сохранился — задание всё равно видно как выполненное */ }
      },

      openConsole: function () {
        this.tab = "console";
        var task = Alpine.store("task");
        if (!task.id) return;
        this.consoleOpenedAt[task.id] = (this.history[task.id] || []).length;
        this.evaluate(false);
      },

      // ---------- Helpers for templates ----------
      statusClass: function (code) {
        if (code >= 200 && code < 300) return "bg-emerald-100 text-emerald-800";
        if (code >= 300 && code < 400) return "bg-sky-100 text-sky-800";
        if (code >= 400 && code < 500) return "bg-amber-100 text-amber-800";
        return "bg-rose-100 text-rose-800";
      },
      pretty: function (text) {
        if (text == null || text === "") return '<span class="text-slate-400">' + window.escapeHtml(t("(пусто)")) + "</span>";
        try { return window.highlightJson(JSON.parse(text)); } catch (e) { return window.escapeHtml(text); }
      },
      prettyHeaders: function (obj) {
        return window.highlightJson(obj);
      },
      ring: function (field) {
        return this.bad[field] ? "ring-2 ring-rose-400" : "";
      },
    };
  });

  function statusText(code) {
    var map = {
      200: "OK", 201: "Created", 204: "No Content", 301: "Moved Permanently", 302: "Found",
      400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
      409: "Conflict", 415: "Unsupported Media Type", 422: "Unprocessable Entity",
      429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway",
      503: "Service Unavailable",
    };
    return map[code] || "";
  }
});
