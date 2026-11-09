// Unit-тесты static/js/task_order.js. Запуск: node --test tests/js/*.test.cjs  (или make test-js)
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const O = require(path.join(__dirname, "../../app/static/js/task_order.js"));

const order = ["a", "b", "c", "d"];

test("firstOpen: ничего не сделано — первое задание", () => {
  assert.equal(O.firstOpen(order, {}), "a");
});

test("firstOpen: часть сделана — первое невыполненное", () => {
  assert.equal(O.firstOpen(order, { a: true, c: true }), "b");
  assert.equal(O.firstOpen(order, { a: true, b: true }), "c");
});

test("firstOpen: всё сделано или заданий нет — свободный режим", () => {
  assert.equal(O.firstOpen(order, { a: true, b: true, c: true, d: true }), null);
  assert.equal(O.firstOpen([], {}), null);
});

test("nextAfter: следующее по порядку, выполненные пропускаются", () => {
  assert.equal(O.nextAfter(order, { a: true }, "a"), "b");
  assert.equal(O.nextAfter(order, { a: true, b: true, c: true }, "a"), "d");
});

test("nextAfter: дальше всё сделано или это последнее — остаёмся (null)", () => {
  assert.equal(O.nextAfter(order, { b: true, c: true, d: true }, "b"), null);
  assert.equal(O.nextAfter(order, {}, "d"), null);
});

test("nextAfter: невыполненные раньше текущего не выбираются", () => {
  assert.equal(O.nextAfter(order, { c: true, d: true }, "c"), null);
});

test("nextAfter: неизвестное задание — null", () => {
  assert.equal(O.nextAfter(order, {}, "zzz"), null);
  assert.equal(O.nextAfter(order, {}, null), null);
});
