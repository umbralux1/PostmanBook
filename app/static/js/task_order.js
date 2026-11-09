// Порядок заданий главы: какое задание выбрать при открытии главы и куда перейти,
// когда задание засчитано. Чистые функции, без DOM — тесты в tests/js/task_order.test.cjs.
//
// order  — id заданий главы по порядку (`order` из YAML);
// passed — { id: true } для засчитанных заданий.
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TaskOrder = api;
})(typeof self !== "undefined" ? self : this, function () {
  // При открытии главы: первое невыполненное; всё сделано — null (свободный режим).
  function firstOpen(order, passed) {
    for (var i = 0; i < order.length; i++) {
      if (!passed[order[i]]) return order[i];
    }
    return null;
  }

  // После засчитанного задания: следующее невыполненное после него по порядку;
  // дальше ничего нет — null (остаёмся на текущем).
  function nextAfter(order, passed, currentId) {
    var i = order.indexOf(currentId);
    if (i === -1) return null;
    for (var j = i + 1; j < order.length; j++) {
      if (!passed[order[j]]) return order[j];
    }
    return null;
  }

  return { firstOpen: firstOpen, nextAfter: nextAfter };
});
