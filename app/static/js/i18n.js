// Перевод строк интерфейса на фронте. Каталог (русская строка → перевод)
// приходит с сервера в window.I18N; для русского он пустой.
(function () {
  var catalog = window.I18N || {};
  window.t = function (text, params) {
    var s = Object.prototype.hasOwnProperty.call(catalog, text) ? catalog[text] : text;
    if (params) {
      s = s.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, function (m, k) {
        return Object.prototype.hasOwnProperty.call(params, k) ? String(params[k]) : m;
      });
    }
    return s;
  };
})();
