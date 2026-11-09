// Минимальная подсветка JSON. Всё экранируется до вставки тегов.
(function () {
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function highlightJson(value) {
    var text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    if (text === undefined) return "";
    var escaped = escapeHtml(text);
    return escaped.replace(
      /(&quot;(?:\\u[a-fA-F0-9]{4}|\\[^u]|(?!&quot;)[^\\])*?&quot;)(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
      function (match, str, colon, lit) {
        if (str) {
          return colon
            ? '<span class="j-key">' + str + "</span>" + colon
            : '<span class="j-str">' + str + "</span>";
        }
        if (lit) return '<span class="j-lit">' + match + "</span>";
        return '<span class="j-num">' + match + "</span>";
      }
    );
  }

  // Ошибка парсинга JSON с номером строки и столбца — для валидации «на лету».
  function jsonError(text) {
    if (!text || !text.trim()) return null;
    try {
      JSON.parse(text);
      return null;
    } catch (e) {
      var msg = e.message || String(e);
      var m = msg.match(/position (\d+)/);
      if (m) {
        var pos = Number(m[1]);
        var before = text.slice(0, pos).split("\n");
        var where = { line: before.length, col: before[before.length - 1].length + 1 };
        msg += " " + (window.t ? window.t("(строка {line}, столбец {col})", where)
                               : "(строка " + where.line + ", столбец " + where.col + ")");
      }
      return msg;
    }
  }

  window.escapeHtml = escapeHtml;
  window.highlightJson = highlightJson;
  window.jsonError = jsonError;
})();
