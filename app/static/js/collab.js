// Совместная работа в комнате: присутствие, курсоры, клики, выделения и
// синхронизация общего мини-Postman через WebSocket /ws/rooms/{code}.
//
// Позиции передаются не в пикселях, а относительно элемента страницы
// (путь от <body> по индексам дочерних элементов + доля ширины/высоты).
// Поэтому курсор попадает «в то же место» даже при разной ширине окна,
// масштабе и языке интерфейса — структура страницы у всех одинаковая.
(function () {
  "use strict";
  var ROOM = window.ROOM;
  if (!ROOM || !window.WebSocket) return;

  var CURSOR_INTERVAL = 33; // ~30 кадров в секунду
  var ws = null;
  var myConn = null;
  var retry = 0;
  var lastSync = {}; // поле → JSON последнего отправленного/полученного значения
  var patchHandler = null;
  var pendingState = null;
  var remotes = {}; // conn → {name, color, cursor, sel, nodes}
  var overlay = null;

  // ---------- Пути к элементам ----------
  function isOverlay(node) {
    return overlay && (node === overlay || overlay.contains(node));
  }

  function pathOf(el) {
    var path = [];
    while (el && el !== document.body) {
      var parent = el.parentElement;
      if (!parent) return null;
      path.unshift(Array.prototype.indexOf.call(parent.children, el));
      el = parent;
    }
    return el === document.body ? path : null;
  }

  function elFromPath(path) {
    var el = document.body;
    for (var i = 0; i < path.length; i++) {
      el = el && el.children[path[i]];
    }
    return el || null;
  }

  // Видимый прямоугольник: если элемент скрыт (x-show), берём ближайшего видимого предка.
  function visibleRect(el) {
    while (el && el !== document.documentElement) {
      var r = el.getBoundingClientRect();
      if (r.width || r.height) return r;
      el = el.parentElement;
    }
    return null;
  }

  function nodeRef(node) {
    if (node.nodeType === 1) return { el: pathOf(node), child: -1 };
    var parent = node.parentElement;
    return { el: pathOf(parent), child: Array.prototype.indexOf.call(parent.childNodes, node) };
  }

  function nodeFromRef(ref) {
    var el = ref && ref.el && elFromPath(ref.el);
    if (!el) return null;
    return ref.child < 0 ? el : el.childNodes[ref.child] || null;
  }

  // ---------- Связь ----------
  function send(msg) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
  }

  function connect() {
    var proto = location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(proto + location.host + "/ws/rooms/" + encodeURIComponent(ROOM.code));
    ws.onopen = function () {
      retry = 0;
      send({ type: "hello", page: location.pathname });
      setConnected(true);
    };
    ws.onmessage = function (e) {
      var msg;
      try { msg = JSON.parse(e.data); } catch (err) { return; }
      dispatch(msg);
    };
    ws.onclose = function () {
      setConnected(false);
      Object.keys(remotes).forEach(removeRemote);
      var delay = Math.min(10000, 500 * Math.pow(2, retry++));
      setTimeout(connect, delay);
    };
  }

  function setConnected(v) {
    if (window.Alpine && Alpine.store("room")) Alpine.store("room").connected = v;
  }

  function dispatch(msg) {
    switch (msg.type) {
      case "welcome":
        myConn = msg.conn;
        updatePresence(msg.presence);
        applyState(msg.state || {});
        break;
      case "presence":
        updatePresence(msg.members);
        break;
      case "patch":
        applyPatch(msg.field, msg.value);
        break;
      case "cursor":
        remote(msg.from).cursor = msg;
        break;
      case "cursor_leave":
        if (remotes[msg.from]) remotes[msg.from].cursor = null;
        if (msg.from && !presenceHas(msg.from)) removeRemote(msg.from);
        break;
      case "click":
        ripple(msg);
        break;
      case "selection":
        remote(msg.from).sel = msg.sel ? { page: msg.page, sel: msg.sel } : null;
        break;
      case "task_completed":
        if (window.Alpine) {
          Alpine.store("task").passed[msg.task_id] = true;
          if (window.htmx) htmx.trigger(document.body, "progress-changed");
        }
        break;
    }
  }

  // ---------- Присутствие ----------
  var presence = [];
  function presenceHas(conn) {
    return presence.some(function (m) { return m.conn === conn; });
  }

  function updatePresence(members) {
    presence = members || [];
    presence.forEach(function (m) {
      if (m.conn === myConn) return;
      var r = remote(m.conn);
      r.name = m.name || t("Гость");
      r.color = m.color;
      r.page = m.page;
    });
    Object.keys(remotes).forEach(function (c) { if (!presenceHas(c)) removeRemote(c); });
    if (window.Alpine && Alpine.store("room")) {
      Alpine.store("room").setMembers(presence, myConn);
    }
  }

  function remote(conn) {
    if (!remotes[conn]) {
      remotes[conn] = { name: "", color: "#6366f1", cursor: null, sel: null, nodes: makeNodes() };
    }
    return remotes[conn];
  }

  function removeRemote(conn) {
    var r = remotes[conn];
    if (!r) return;
    r.nodes.cursor.remove();
    r.nodes.sel.remove();
    delete remotes[conn];
  }

  // ---------- Общее состояние мини-Postman ----------
  function applyState(state) {
    if (!patchHandler) { pendingState = state; return; }
    Object.keys(state).forEach(function (f) { applyPatch(f, state[f]); });
  }

  function applyPatch(field, value) {
    lastSync[field] = JSON.stringify(value === undefined ? null : value);
    if (!patchHandler) {
      pendingState = pendingState || {};
      pendingState[field] = value;
      return;
    }
    patchHandler(field, value);
  }

  // ---------- Курсоры ----------
  var lastCursorAt = 0;
  var lastPointer = null;
  var trailing = null;
  function onPointerMove(e) {
    lastPointer = { clientX: e.clientX, clientY: e.clientY };
    var now = Date.now();
    var wait = CURSOR_INTERVAL - (now - lastCursorAt);
    if (wait > 0) {
      // Не чаще ~30 раз в секунду, но последняя позиция отправляется всегда.
      if (!trailing) {
        trailing = setTimeout(function () {
          trailing = null;
          lastCursorAt = Date.now();
          sendPointer("cursor", lastPointer);
        }, wait);
      }
      return;
    }
    lastCursorAt = now;
    sendPointer("cursor", lastPointer);
  }

  function pointerMsg(type, e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || isOverlay(el)) return null;
    var r = el.getBoundingClientRect();
    var path = pathOf(el);
    if (!path || !r.width || !r.height) return null;
    return {
      type: type,
      page: location.pathname,
      path: path,
      rx: +((e.clientX - r.left) / r.width).toFixed(4),
      ry: +((e.clientY - r.top) / r.height).toFixed(4),
    };
  }

  function sendPointer(type, e) {
    var msg = pointerMsg(type, e);
    if (msg) send(msg);
  }

  function pointToViewport(msg) {
    if (!msg || msg.page !== location.pathname) return null;
    var el = elFromPath(msg.path);
    var r = el && visibleRect(el);
    if (!r) return null;
    return { x: r.left + msg.rx * r.width, y: r.top + msg.ry * r.height };
  }

  // ---------- Клики ----------
  function onPointerDown(e) {
    sendPointer("click", e);
  }

  function ripple(msg) {
    var p = pointToViewport(msg);
    var r = remotes[msg.from];
    if (!p || !r) return;
    var d = document.createElement("div");
    d.className = "collab-ripple";
    d.style.left = p.x + "px";
    d.style.top = p.y + "px";
    d.style.borderColor = r.color;
    overlay.appendChild(d);
    setTimeout(function () { d.remove(); }, 700);
  }

  // ---------- Выделение текста и каретка ----------
  var lastSel = "null";
  var selScheduled = false;
  function scheduleSelection() {
    if (selScheduled) return;
    selScheduled = true;
    requestAnimationFrame(function () {
      selScheduled = false;
      var sel = currentSelection();
      var json = JSON.stringify(sel);
      if (json === lastSel) return;
      lastSel = json;
      send({ type: "selection", page: location.pathname, sel: sel });
    });
  }

  function isTextField(el) {
    if (!el) return false;
    if (el.tagName === "TEXTAREA") return true;
    return el.tagName === "INPUT" && /^(text|search|url|email|)$/.test(el.type || "");
  }

  function currentSelection() {
    var active = document.activeElement;
    if (isTextField(active)) {
      var p = pathOf(active);
      if (!p) return null;
      return { kind: "field", path: p, start: active.selectionStart, end: active.selectionEnd };
    }
    var s = window.getSelection();
    if (!s || !s.rangeCount || s.isCollapsed) return null;
    var range = s.getRangeAt(0);
    if (isOverlay(range.commonAncestorContainer)) return null;
    var a = nodeRef(range.startContainer);
    var b = nodeRef(range.endContainer);
    if (!a.el || !b.el) return null;
    return { kind: "range", start: a, so: range.startOffset, end: b, eo: range.endOffset };
  }

  var MIRROR_PROPS = [
    "boxSizing", "width", "height", "overflowX", "overflowY",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "borderStyle",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "fontStyle", "fontVariant", "fontWeight", "fontStretch", "fontSize", "lineHeight",
    "fontFamily", "textAlign", "textTransform", "textIndent", "letterSpacing", "wordSpacing", "tabSize",
  ];

  // Прямоугольники участка текста внутри input/textarea (через «зеркальный» div).
  function fieldRects(field, start, end) {
    var box = field.getBoundingClientRect();
    if (!box.width) return { rects: [], box: box };
    var cs = getComputedStyle(field);
    var m = document.createElement("div");
    MIRROR_PROPS.forEach(function (p) { m.style[p] = cs[p]; });
    m.style.position = "fixed";
    m.style.left = box.left + "px";
    m.style.top = box.top + "px";
    m.style.visibility = "hidden";
    m.style.overflow = "hidden";
    m.style.borderColor = "transparent";
    var isArea = field.tagName === "TEXTAREA";
    m.style.whiteSpace = isArea ? "pre-wrap" : "pre";
    m.style.wordWrap = isArea ? "break-word" : "normal";
    var v = field.value;
    start = Math.max(0, Math.min(start, v.length));
    end = Math.max(start, Math.min(end, v.length));
    m.appendChild(document.createTextNode(v.slice(0, start)));
    var span = document.createElement("span");
    span.textContent = v.slice(start, end) || "​";
    m.appendChild(span);
    m.appendChild(document.createTextNode(v.slice(end) + (isArea ? "\n" : "")));
    document.body.appendChild(m);
    m.scrollTop = field.scrollTop;
    m.scrollLeft = field.scrollLeft;
    var rects = Array.prototype.map.call(span.getClientRects(), function (r) {
      return { left: r.left, top: r.top, width: start === end ? 2 : r.width, height: r.height };
    });
    m.remove();
    // Обрезаем по видимой области поля.
    rects = rects.filter(function (r) {
      return r.top + r.height > box.top && r.top < box.bottom &&
             r.left + r.width >= box.left && r.left <= box.right;
    });
    return { rects: rects, box: box };
  }

  function selectionRects(entry) {
    if (!entry || entry.page !== location.pathname) return [];
    var sel = entry.sel;
    if (sel.kind === "field") {
      var field = elFromPath(sel.path);
      if (!isTextField(field)) return [];
      return fieldRects(field, sel.start, sel.end).rects;
    }
    var a = nodeFromRef(sel.start);
    var b = nodeFromRef(sel.end);
    if (!a || !b) return [];
    try {
      var range = document.createRange();
      range.setStart(a, Math.min(sel.so, a.length !== undefined ? a.length : a.childNodes.length));
      range.setEnd(b, Math.min(sel.eo, b.length !== undefined ? b.length : b.childNodes.length));
      return Array.prototype.slice.call(range.getClientRects());
    } catch (e) {
      return [];
    }
  }

  // ---------- Отрисовка ----------
  function makeNodes() {
    ensureOverlay();
    var cursor = document.createElement("div");
    cursor.className = "collab-cursor";
    cursor.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">' +
      '<path d="M2 1 L2 15 L6 11 L9 17 L11.5 16 L8.5 10 L14 10 Z" stroke="white" stroke-width="1.2"/></svg>' +
      '<span class="collab-label"></span>';
    cursor.style.display = "none";
    var sel = document.createElement("div");
    overlay.appendChild(sel);
    overlay.appendChild(cursor);
    return { cursor: cursor, sel: sel };
  }

  function ensureOverlay() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "collab-overlay";
    overlay.setAttribute("aria-hidden", "true");
    document.body.appendChild(overlay);
  }

  function render() {
    Object.keys(remotes).forEach(function (conn) {
      var r = remotes[conn];
      var n = r.nodes;
      // Курсор
      var p = pointToViewport(r.cursor);
      if (p) {
        n.cursor.style.display = "";
        n.cursor.style.transform = "translate(" + p.x + "px," + p.y + "px)";
        n.cursor.querySelector("path").setAttribute("fill", r.color);
        var label = n.cursor.querySelector(".collab-label");
        label.textContent = r.name;
        label.style.background = r.color;
      } else {
        n.cursor.style.display = "none";
      }
      // Выделение / каретка
      var rects = selectionRects(r.sel);
      while (n.sel.children.length > rects.length) n.sel.lastChild.remove();
      while (n.sel.children.length < rects.length) {
        var d = document.createElement("div");
        d.className = "collab-sel";
        n.sel.appendChild(d);
      }
      rects.forEach(function (rc, i) {
        var d = n.sel.children[i];
        d.style.left = rc.left + "px";
        d.style.top = rc.top + "px";
        d.style.width = Math.max(2, rc.width) + "px";
        d.style.height = rc.height + "px";
        d.style.background = r.color;
        d.style.opacity = rc.width <= 2 ? "0.9" : "0.25";
      });
    });
    requestAnimationFrame(render);
  }

  // ---------- Публичный API для мини-Postman ----------
  window.Collab = {
    // Локальное изменение общего поля → разослать (если это не эхо удалённого изменения).
    local: function (field, value) {
      var json = JSON.stringify(value === undefined ? null : value);
      if (lastSync[field] === json) return;
      lastSync[field] = json;
      send({ type: "patch", field: field, value: value === undefined ? null : value });
    },
    // Регистрация получателя удалённых изменений (компонент мини-Postman).
    onPatch: function (handler) {
      patchHandler = handler;
      if (pendingState) {
        var s = pendingState;
        pendingState = null;
        applyState(s);
      }
    },
    // Запомнить значение как уже синхронизированное (без отправки).
    seed: function (field, value) {
      if (lastSync[field] === undefined) lastSync[field] = JSON.stringify(value === undefined ? null : value);
    },
  };

  // ---------- Помощники для шаблонов ----------
  window.CollabUI = {
    initials: function (name) {
      var parts = String(name || "?").trim().split(/\s+/);
      return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
    },
    pageLabel: function (page) {
      if (page === "/") return t("на главной");
      var m = /^\/chapters\/([^/]+)/.exec(page || "");
      if (m) return t("в главе {id}", { id: m[1] });
      return t("на другой странице");
    },
  };

  // ---------- Старт ----------
  document.addEventListener("alpine:init", function () {
    Alpine.data("roomWidget", function () {
      return {
        openInvite: false,
        copied: false,
        inviteLink: function () {
          return location.origin + "/join/" + encodeURIComponent(ROOM.code);
        },
        copy: function () {
          var self = this;
          var done = function () {
            self.copied = true;
            setTimeout(function () { self.copied = false; }, 2000);
          };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(this.inviteLink()).then(done, function () {});
          }
        },
        memberTitle: function (m) {
          return m.name + (m.isMe ? " (" + t("ты") + ")" : "") + " — " + CollabUI.pageLabel(m.page);
        },
        roomLabel: function () {
          var room = Alpine.store("room");
          if (room.own) return t("Твоя комната");
          return t("Комната: {name}", { name: room.ownerName || t("Гость") });
        },
      };
    });

    Alpine.data("nameDialog", function () {
      return {
        open: !ROOM.me.name,
        name: ROOM.me.name || "",
        error: "",
        init: function () {
          var self = this;
          if (this.open) this.$nextTick(function () { self.$refs.input.focus(); });
        },
        canClose: function () { return Boolean(Alpine.store("room").me.name); },
        edit: function () {
          this.name = Alpine.store("room").me.name || "";
          this.open = true;
          var self = this;
          this.$nextTick(function () { self.$refs.input.focus(); });
        },
        save: async function () {
          this.error = "";
          try {
            var res = await fetch("/api/me", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: this.name }),
              credentials: "same-origin",
            });
            var data = await res.json();
            if (!res.ok) { this.error = data.message || t("Укажи имя."); return; }
            Alpine.store("room").me.name = data.name;
            ROOM.me.name = data.name;
            this.open = false;
          } catch (e) {
            this.error = t("Не получилось сохранить, попробуй ещё раз.");
          }
        },
      };
    });

    Alpine.store("room", {
      code: ROOM.code,
      own: ROOM.own,
      ownerName: ROOM.owner_name,
      me: ROOM.me,
      members: [],
      connected: false,
      setMembers: function (list, mine) {
        // Один человек может открыть несколько вкладок — показываем его один раз.
        var seen = {};
        this.members = list.filter(function (m) {
          if (seen[m.user_id]) return false;
          seen[m.user_id] = true;
          return true;
        }).map(function (m) {
          return Object.assign({}, m, {
            name: m.name || t("Гость"),
            isMe: m.user_id === ROOM.me.id || m.conn === mine,
          });
        });
      },
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    ensureOverlay();
    connect();
    document.addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("pointerdown", onPointerDown, { capture: true, passive: true });
    document.documentElement.addEventListener("pointerleave", function () {
      send({ type: "cursor_leave" });
    });
    // Прокрутка меняет, над каким элементом курсор, — пересчитываем.
    window.addEventListener("scroll", function () {
      if (lastPointer) onPointerMove(lastPointer);
    }, { passive: true });
    ["selectionchange", "keyup", "mouseup", "input", "focusin", "focusout", "scroll"].forEach(function (ev) {
      document.addEventListener(ev, scheduleSelection, true);
    });
    requestAnimationFrame(render);
  });
})();
