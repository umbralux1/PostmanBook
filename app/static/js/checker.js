// Проверка задания по ответу сервера — чистые функции, без DOM и сети.
//
// Ответ, который проверяем:
//   { status: 200, headers: {"content-type": "..."}, body: <JSON или текст> }
//
// Ожидания задаются в YAML задания (поле expected) списком утверждений:
//   { path: "body.args.user", equals: "student", hint: "..." }
// Операторы: equals | contains | exists | in.
// contains: подстрока в строке или элемент массива; если значение — объект, в массиве
// должен быть элемент с этими полями (остальные поля элемента не важны):
//   { path: "body.items", contains: { title: "SMS code not received" } }
// path начинается с status, headers или body; дальше — ключи через точку.
//
// Варианты задания:
//   response: [...]                 — один ответ должен удовлетворить всем утверждениям;
//   steps: [[...], [...]]           — несколько ответов, каждый шаг — свой список утверждений;
//   ordered: true                   — шаги должны выполняться по порядку;
//   require_console: true           — после выполнения нужно открыть Console (кнопка в нижней строке мини-Postman).
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TaskChecker = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MISSING = { missing: true };

  // Перевод встроенных сообщений. В браузере берётся window.t (static/js/i18n.js),
  // в тестах можно подставить свой через setTranslator().
  var customTranslator = null;
  function fmt(text, params) {
    return String(text).replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, function (m, k) {
      return params && Object.prototype.hasOwnProperty.call(params, k) ? String(params[k]) : m;
    });
  }
  function tr(text, params) {
    if (customTranslator) return customTranslator(text, params);
    if (typeof self !== "undefined" && typeof self.t === "function") return self.t(text, params);
    return fmt(text, params);
  }
  function setTranslator(fn) { customTranslator = fn; }

  function getPath(response, path) {
    var parts = String(path).split(".");
    var root = parts.shift();
    var cur;
    if (root === "status") cur = response.status;
    else if (root === "headers") cur = response.headers || {};
    else if (root === "body") cur = response.body;
    else return MISSING;

    for (var i = 0; i < parts.length; i++) {
      var key = parts[i];
      if (root === "headers" && i === 0) key = key.toLowerCase();
      if (cur !== null && typeof cur === "object" && Object.prototype.hasOwnProperty.call(cur, key)) {
        cur = cur[key];
      } else {
        return MISSING;
      }
    }
    return cur === undefined ? MISSING : cur;
  }

  function deepEqual(a, b) {
    if (a === b) return true;
    if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    var ka = Object.keys(a);
    var kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    for (var i = 0; i < ka.length; i++) {
      if (!Object.prototype.hasOwnProperty.call(b, ka[i]) || !deepEqual(a[ka[i]], b[ka[i]])) return false;
    }
    return true;
  }

  // Элемент массива подходит под contains: равен значению или (для объекта) содержит его поля.
  function includes(item, want) {
    if (want === null || typeof want !== "object" || Array.isArray(want)) return deepEqual(item, want);
    if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
    return Object.keys(want).every(function (k) {
      return Object.prototype.hasOwnProperty.call(item, k) && deepEqual(item[k], want[k]);
    });
  }

  function show(v) {
    if (v === MISSING) return tr("(нет такого поля)");
    return JSON.stringify(v);
  }

  function checkAssertion(a, response) {
    var actual = getPath(response, a.path);
    var found = actual !== MISSING;
    var ok;
    var op;
    var expected;
    if (Object.prototype.hasOwnProperty.call(a, "equals")) {
      op = "equals";
      expected = a.equals;
      ok = found && deepEqual(actual, a.equals);
    } else if (Object.prototype.hasOwnProperty.call(a, "contains")) {
      op = "contains";
      expected = a.contains;
      if (typeof actual === "string") ok = actual.indexOf(a.contains) !== -1;
      else if (Array.isArray(actual)) ok = actual.some(function (x) { return includes(x, a.contains); });
      else ok = false;
    } else if (Object.prototype.hasOwnProperty.call(a, "exists")) {
      op = "exists";
      expected = a.exists;
      ok = (found && actual !== null) === Boolean(a.exists);
    } else if (Object.prototype.hasOwnProperty.call(a, "in")) {
      op = "in";
      expected = a["in"];
      ok = found && a["in"].some(function (x) { return deepEqual(x, actual); });
    } else {
      throw new Error("Неизвестный оператор в проверке " + a.path);
    }
    return {
      path: a.path,
      op: op,
      ok: ok,
      expected: expected,
      found: found,
      actual: found ? actual : null,
      message: ok ? "" : (a.hint || defaultMessage(a.path, op, expected, actual)),
    };
  }

  function defaultMessage(path, op, expected, actual) {
    var v = JSON.stringify(expected);
    var what = {
      equals: tr("должно быть {value}", { value: v }),
      contains: tr("должно содержать {value}", { value: v }),
      exists: expected ? tr("должно присутствовать") : tr("должно отсутствовать"),
      "in": tr("должно быть одним из {value}", { value: v }),
    }[op];
    return tr("В ответе {path} {what}, а пришло {actual}.", { path: path, what: what, actual: show(actual) });
  }

  function checkResponse(assertions, response) {
    var results = assertions.map(function (a) { return checkAssertion(a, response); });
    var failed = results.filter(function (r) { return !r.ok; });
    return { ok: failed.length === 0, results: results, failed: failed };
  }

  function stepsOf(expected) {
    if (expected.steps) return expected.steps;
    if (expected.response) return [expected.response];
    throw new Error("В задании нет response или steps");
  }

  // history — ответы по этому заданию, старые → новые.
  // state.consoleOpenedAt — длина history в момент открытия Console (или null).
  function evaluateTask(expected, history, state) {
    var steps = stepsOf(expected);
    var n = steps.length;
    var latest = history.length ? history[history.length - 1] : null;
    state = state || {};

    // Сколько шагов выполнено и на каком ответе выполнен последний.
    var done = 0;
    var completedAt = -1;
    var doneFlags = steps.map(function () { return false; });
    if (expected.ordered) {
      for (var i = 0; i < history.length && done < n; i++) {
        if (checkResponse(steps[done], history[i]).ok) {
          doneFlags[done] = true;
          done++;
          if (done === n) completedAt = i;
        }
      }
    } else {
      for (var j = 0; j < history.length; j++) {
        for (var s = 0; s < n; s++) {
          if (!doneFlags[s] && checkResponse(steps[s], history[j]).ok) {
            doneFlags[s] = true;
            done++;
            if (done === n && completedAt < 0) completedAt = j;
          }
        }
      }
    }

    var result = {
      passed: false,
      done: done,
      total: n,
      results: [],
      hint: "",
      waitingConsole: false,
    };
    if (!latest) return result;

    // Какой шаг показываем пользователю для последнего ответа.
    var focus;
    if (done === n) {
      focus = null;
    } else if (expected.ordered) {
      focus = steps[done];
    } else {
      var best = null;
      for (var k = 0; k < n; k++) {
        if (doneFlags[k]) continue;
        var r = checkResponse(steps[k], latest);
        if (!best || r.failed.length < best.failed.length) best = r;
      }
      focus = best;
    }

    if (focus === null) {
      // Последний подходящий шаг — показываем его результаты.
      var lastOk = null;
      for (var m = 0; m < n; m++) {
        var rr = checkResponse(steps[m], latest);
        if (rr.ok) { lastOk = rr; break; }
      }
      result.results = lastOk ? lastOk.results : [];
      if (expected.require_console) {
        var opened = state.consoleOpenedAt;
        if (opened === null || opened === undefined || opened < completedAt + 1) {
          result.waitingConsole = true;
          result.hint = expected.console_hint || tr("Теперь открой Console: кнопка в нижней строке мини-Postman.");
          return result;
        }
      }
      result.passed = true;
      return result;
    }

    var check = Array.isArray(focus) ? checkResponse(focus, latest) : focus;
    result.results = check.results;
    result.hint = check.failed.length ? check.failed[0].message : "";
    return result;
  }

  // Ответ fetch() → объект для проверки.
  function normalizeResponse(status, headerPairs, text) {
    var headers = {};
    (headerPairs || []).forEach(function (p) { headers[String(p[0]).toLowerCase()] = p[1]; });
    var body = text;
    if (typeof text === "string" && text.trim()) {
      try { body = JSON.parse(text); } catch (e) { body = text; }
    } else if (text === "") {
      body = null;
    }
    return { status: status, headers: headers, body: body };
  }

  return {
    getPath: getPath,
    checkAssertion: checkAssertion,
    checkResponse: checkResponse,
    evaluateTask: evaluateTask,
    normalizeResponse: normalizeResponse,
    setTranslator: setTranslator,
  };
});
