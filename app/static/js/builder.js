// Мини-Postman (фаза 1): собирает запрос, отправляет fetch() на учебный API,
// показывает ответ, ведёт журнал (Console) и получает результат проверки задания.
// Выбор задания и автопереход — Alpine.store("task") в task_store.js.
document.addEventListener("alpine:init", function () {
  // Поля мини-Postman, общие для всех в комнате (сервер принимает только их).
  var SHARED_FIELDS = [
    "method", "url", "params", "headers", "bodyMode", "body",
    "tab", "respTab", "respView", "openedLog", "sending", "response", "log", "history", "consoleOpenedAt",
    "requestTabs", "activeTab", "consoleOpen",
  ];
  // Поля, которые у каждой вкладки запроса свои (как в Postman). Console (log, consoleOpen),
  // история ответов для проверки и выбранное задание — общие для всех вкладок.
  var TAB_FIELDS = ["method", "url", "params", "headers", "bodyMode", "body", "tab", "respTab", "respView", "response"];
  var MAX_TABS = 10;
  // Цвета методов — как в Postman.
  var METHOD_COLORS = {
    GET: "#007f31", POST: "#ad7a03", PUT: "#0053b8", PATCH: "#623497", DELETE: "#8e1a10",
  };
  var DEFAULTS = {
    method: function () { return "GET"; },
    url: function () { return window.location.origin + "/api/echo"; },
    params: function () { return [{ key: "", value: "" }]; },
    headers: function () { return [{ key: "", value: "" }]; },
    bodyMode: function () { return "none"; },
    body: function () { return ""; },
    tab: function () { return "params"; },
    respTab: function () { return "body"; },
    respView: function () { return "pretty"; },
    openedLog: function () { return null; },
    sending: function () { return false; },
    response: function () { return null; },
    log: function () { return []; },
    history: function () { return {}; },
    consoleOpenedAt: function () { return {}; },
    requestTabs: function () { return [newTab(window.location.origin + "/api/echo")]; },
    activeTab: function () { return null; },
    consoleOpen: function () { return false; },
  };

  function tabId() {
    return "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }
  // Вкладка хранит снимок полей запроса; у активной вкладки живые значения — в компоненте.
  function newTab(url) {
    return {
      id: tabId(),
      data: {
        method: "GET", url: url || "", params: [{ key: "", value: "" }],
        headers: [{ key: "", value: "" }], bodyMode: "none", body: "",
        tab: "params", respTab: "body", respView: "pretty", response: null,
      },
    };
  }
  function clone(v) { return JSON.parse(JSON.stringify(v === undefined ? null : v)); }
  var HEADER_NAMES = ["Content-Type", "Accept", "Authorization", "X-Debug-Source", "Cache-Control"];
  var MAX_LOG = 10;

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
      respView: "pretty",
      sending: false,
      error: null,
      response: null,
      log: [],
      openedLog: null,
      validation: null,
      bad: {},
      history: {},          // id задания → ответы сервера (старые → новые)
      consoleOpenedAt: {},  // id задания → сколько ответов было, когда открыли Console
      requestTabs: [],      // вкладки запросов: [{id, data}]
      activeTab: null,      // id активной вкладки
      consoleOpen: false,   // открыта ли панель Console (кнопка в нижней строке)

      init: function () {
        this.syncParamsFromUrl();
        var first = newTab(this.url);
        this.requestTabs = [first];
        this.activeTab = first.id;
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
          var store = Alpine.store("task");
          if ((window.TASKS || {})[value]) store.selectById(value, true);
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
        if (field === "requestTabs" || field === "activeTab") this.fixActiveTab();
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

      // ---------- Вкладки запросов ----------
      saveActiveTab: function () {
        var self = this;
        var t = this.requestTabs.find(function (x) { return x.id === self.activeTab; });
        if (!t) return;
        var data = {};
        TAB_FIELDS.forEach(function (f) { data[f] = clone(self[f]); });
        t.data = data;
      },
      loadTab: function (t) {
        var self = this;
        TAB_FIELDS.forEach(function (f) {
          self[f] = t.data[f] === undefined || t.data[f] === null ? DEFAULTS[f]() : clone(t.data[f]);
        });
        this.activeTab = t.id;
        this.error = null;
      },
      // Активная вкладка должна существовать (например, в комнате ещё нет вкладок).
      fixActiveTab: function () {
        if (!Array.isArray(this.requestTabs) || !this.requestTabs.length) this.requestTabs = DEFAULTS.requestTabs();
        var self = this;
        if (!this.requestTabs.some(function (x) { return x.id === self.activeTab; })) this.activeTab = this.requestTabs[0].id;
      },
      selectTab: function (id) {
        if (this.sending || id === this.activeTab) return;
        var t = this.requestTabs.find(function (x) { return x.id === id; });
        if (!t) return;
        this.saveActiveTab();
        this.loadTab(t);
      },
      addTab: function () {
        if (this.sending || this.requestTabs.length >= MAX_TABS) return;
        this.saveActiveTab();
        var t = newTab("");
        this.requestTabs.push(t);
        this.loadTab(t);
      },
      closeTab: function (id) {
        if (this.sending) return;
        var i = this.requestTabs.findIndex(function (x) { return x.id === id; });
        if (i < 0) return;
        var wasActive = id === this.activeTab;
        if (!wasActive) this.saveActiveTab();
        this.requestTabs.splice(i, 1);
        if (!this.requestTabs.length) this.requestTabs.push(newTab(""));
        if (wasActive) this.loadTab(this.requestTabs[Math.min(i, this.requestTabs.length - 1)]);
      },
      // Подпись вкладки: как в Postman, у несохранённого запроса — его URL.
      tabLabel: function (t) {
        var url = t.id === this.activeTab ? this.url : t.data.url;
        return (url || "").trim() || "Untitled Request";
      },
      tabMethod: function (t) {
        return t.id === this.activeTab ? this.method : t.data.method;
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
          entry.timeMs = timeMs;
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
        // Console уже открыта — ответ сразу виден в журнале, повторно открывать не нужно.
        if (this.consoleOpen) this.consoleOpenedAt[task.id] = list.length;
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
        task.advanceFrom(taskId);
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

      // Кнопка Console в нижней строке: открывает и закрывает журнал.
      // Открытие засчитывается заданиям с require_console.
      toggleConsole: function () {
        this.consoleOpen = !this.consoleOpen;
        if (this.consoleOpen) this.markConsoleOpened();
      },
      markConsoleOpened: function () {
        var task = Alpine.store("task");
        if (!task.id) return;
        this.consoleOpenedAt[task.id] = (this.history[task.id] || []).length;
        this.evaluate(false);
      },

      // ---------- Helpers for templates ----------
      // Цвета как в Postman: 2xx зелёный, 3xx синий, 4xx/5xx красный.
      statusClass: function (code) {
        if (code >= 200 && code < 300) return "pm-ok";
        if (code >= 300 && code < 400) return "pm-redirect";
        return "pm-fail";
      },
      methodColor: function (method) {
        return METHOD_COLORS[method] || "#212121";
      },
      lineNumbers: function (text) {
        var n = String(text || "").split("\n").length;
        var out = [];
        for (var i = 1; i <= n; i++) out.push(i);
        return out.join("\n");
      },
      // Тело ответа в режиме Pretty: JSON с отступами, иначе как есть.
      prettyText: function (text) {
        if (text == null || text === "") return "";
        try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return String(text); }
      },
      pretty: function (text) {
        if (text == null || text === "") return '<span style="color:#a6a6a6">' + window.escapeHtml(t("(пусто)")) + "</span>";
        try { return window.highlightJson(JSON.parse(text)); } catch (e) { return window.escapeHtml(text); }
      },
      prettyHeaders: function (obj) {
        return window.highlightJson(obj);
      },
      formatSize: function (bytes) {
        return bytes < 1024 ? bytes + " B" : (bytes / 1024).toFixed(2) + " KB";
      },
      ring: function (field) {
        return this.bad[field] ? "is-bad" : "";
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
