// Unit-тесты static/js/checker.js. Запуск: node --test tests/js/*.test.cjs  (или make test-js)
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const C = require(path.join(__dirname, "../../app/static/js/checker.js"));

// Ответ echo-сервера на GET /api/echo?source=postman&user=student
const echoGet = {
  status: 200,
  headers: { "content-type": "application/json" },
  body: {
    method: "GET",
    path: "/api/echo",
    args: { source: "postman", user: "student" },
    headers: { "content-type": "application/json", "x-debug-source": "support-training" },
    json: null,
  },
};

const resp = (status, body) => ({ status, headers: {}, body });

test("getPath: status, вложенные поля, заголовки без учёта регистра", () => {
  assert.equal(C.getPath(echoGet, "status"), 200);
  assert.equal(C.getPath(echoGet, "body.args.user"), "student");
  assert.equal(C.getPath(echoGet, "headers.Content-Type"), "application/json");
  assert.equal(C.getPath(echoGet, "body.json"), null);
  assert.equal(C.getPath(echoGet, "body.args.nope").missing, true);
  assert.equal(C.getPath(echoGet, "body.args.user.deeper").missing, true);
  assert.equal(C.getPath(echoGet, "cookies.x").missing, true);
});

test("equals строгий: строка \"123\" не равна числу 123", () => {
  const r = { status: 200, headers: {}, body: { json: { id: 123 } } };
  assert.equal(C.checkAssertion({ path: "body.json.id", equals: "123" }, r).ok, false);
  assert.equal(C.checkAssertion({ path: "body.json.id", equals: 123 }, r).ok, true);
});

test("contains, exists, in", () => {
  const r = { status: 200, headers: {}, body: { ct: "application/json; charset=utf-8", tags: ["a", "b"], n: null } };
  assert.equal(C.checkAssertion({ path: "body.ct", contains: "application/json" }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "body.tags", contains: "b" }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "body.missing", contains: "x" }, r).ok, false);
  assert.equal(C.checkAssertion({ path: "body.ct", exists: true }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "body.n", exists: true }, r).ok, false, "null считается отсутствием");
  assert.equal(C.checkAssertion({ path: "body.missing", exists: false }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "status", in: [200, 201] }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "status", in: ["200"] }, r).ok, false);
});

test("неизвестный оператор — ошибка автора контента, а не тихий pass", () => {
  assert.throws(() => C.checkAssertion({ path: "status", greater: 1 }, echoGet));
});

test("подсказка: из YAML, а если её нет — понятный текст по умолчанию", () => {
  const withHint = C.checkAssertion({ path: "body.args.user", equals: "x", hint: "Добавь user" }, echoGet);
  assert.equal(withHint.message, "Добавь user");
  const noHint = C.checkAssertion({ path: "body.args.page", equals: "2" }, echoGet);
  assert.match(noHint.message, /body\.args\.page/);
  assert.match(noHint.message, /нет такого поля/);
});

test("один ответ: pass и подсказка первого несовпадения", () => {
  const expected = {
    response: [
      { path: "status", equals: 200, hint: "h-status" },
      { path: "body.method", equals: "GET", hint: "h-method" },
      { path: "body.args.user", equals: "student", hint: "h-user" },
    ],
  };
  assert.equal(C.evaluateTask(expected, [echoGet]).passed, true);

  const post = structuredClone(echoGet);
  post.body.method = "POST";
  delete post.body.args.user;
  const v = C.evaluateTask(expected, [post]);
  assert.equal(v.passed, false);
  assert.equal(v.hint, "h-method");
  assert.deepEqual(v.results.map((r) => r.ok), [true, false, false]);
});

test("без ответов — ничего не засчитано и подсказки нет", () => {
  const v = C.evaluateTask({ response: [{ path: "status", equals: 200 }] }, []);
  assert.equal(v.passed, false);
  assert.equal(v.hint, "");
});

test("steps без порядка: засчитывается, когда пришли все ответы", () => {
  const expected = {
    steps: [
      [{ path: "status", equals: 200, hint: "send 200" }],
      [{ path: "status", equals: 404, hint: "send 404" }],
      [{ path: "status", equals: 500, hint: "send 500" }],
    ],
  };
  let v = C.evaluateTask(expected, [resp(500, {})]);
  assert.equal(v.done, 1);
  assert.equal(v.hint, "send 200");
  v = C.evaluateTask(expected, [resp(500, {}), resp(200, {})]);
  assert.equal(v.done, 2);
  assert.equal(v.hint, "send 404");
  v = C.evaluateTask(expected, [resp(500, {}), resp(200, {}), resp(404, {})]);
  assert.equal(v.passed, true);
  assert.equal(v.done, 3);
});

test("steps по порядку: успех без предварительной ошибки не засчитывается", () => {
  const expected = {
    ordered: true,
    steps: [
      [{ path: "status", equals: 400, hint: "сначала сломай" }],
      [{ path: "status", equals: 200, hint: "теперь почини" }],
    ],
  };
  let v = C.evaluateTask(expected, [resp(200, {})]);
  assert.equal(v.passed, false);
  assert.equal(v.hint, "сначала сломай");
  v = C.evaluateTask(expected, [resp(200, {}), resp(400, {})]);
  assert.equal(v.done, 1);
  assert.equal(v.hint, "теперь почини");
  v = C.evaluateTask(expected, [resp(200, {}), resp(400, {}), resp(200, {})]);
  assert.equal(v.passed, true);
});

test("require_console: Console нужно открыть после правильного ответа", () => {
  const expected = {
    response: [{ path: "status", equals: 200 }],
    require_console: true,
    console_hint: "открой Console",
  };
  let v = C.evaluateTask(expected, [echoGet], { consoleOpenedAt: null });
  assert.equal(v.passed, false);
  assert.equal(v.waitingConsole, true);
  assert.equal(v.hint, "открой Console");
  // Открыли Console до запроса — не считается.
  v = C.evaluateTask(expected, [echoGet], { consoleOpenedAt: 0 });
  assert.equal(v.passed, false);
  v = C.evaluateTask(expected, [echoGet], { consoleOpenedAt: 1 });
  assert.equal(v.passed, true);
});

test("normalizeResponse: JSON, текст, пустое тело, заголовки в нижнем регистре", () => {
  const r = C.normalizeResponse(200, [["Content-Type", "application/json"]], '{"a": 1}');
  assert.deepEqual(r, { status: 200, headers: { "content-type": "application/json" }, body: { a: 1 } });
  assert.equal(C.normalizeResponse(500, [], "oops").body, "oops");
  assert.equal(C.normalizeResponse(204, [], "").body, null);
});

test("встроенные сообщения переводятся через setTranslator", () => {
  const en = {
    "В ответе {path} {what}, а пришло {actual}.": "In the response, {path} {what}, but got {actual}.",
    "должно быть {value}": "should be {value}",
    "(нет такого поля)": "(no such field)",
  };
  C.setTranslator((text, params) =>
    (en[text] || text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)),
  );
  try {
    const r = C.checkAssertion({ path: "body.args.page", equals: "2" }, echoGet);
    assert.equal(r.message, 'In the response, body.args.page should be "2", but got (no such field).');
  } finally {
    C.setTranslator(null);
  }
  assert.match(C.checkAssertion({ path: "body.args.page", equals: "2" }, echoGet).message, /В ответе/);
});

test("contains с объектом: в массиве есть элемент с этими полями", () => {
  const r = resp(200, { items: [{ id: 1, title: "A", status: "open" }, { id: 2, title: "B" }], tags: ["x"] });
  assert.equal(C.checkAssertion({ path: "body.items", contains: { title: "B" } }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "body.items", contains: { title: "A", status: "open" } }, r).ok, true);
  assert.equal(C.checkAssertion({ path: "body.items", contains: { title: "A", status: "closed" } }, r).ok, false);
  assert.equal(C.checkAssertion({ path: "body.items", contains: { title: "C" } }, r).ok, false);
  assert.equal(C.checkAssertion({ path: "body.tags", contains: { title: "x" } }, r).ok, false);
  assert.equal(C.checkAssertion({ path: "body.tags", contains: "x" }, r).ok, true);
});
