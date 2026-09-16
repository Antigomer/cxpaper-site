/* The license desk. Reads the Worker's admin data and draws it.
 *
 * No chart library. The rest of this site carries none, and two charts do not
 * justify 300 KB of somebody else's JavaScript. The SVG is written by hand.
 *
 * The reading at the top is generated from the numbers, not written by anyone:
 * Chris asked for an interpretation with as little involvement from him as
 * possible, and a sentence that is computed cannot go stale the way a sentence
 * someone typed once does. Every claim it makes is one the data supports.
 */
(function () {
  "use strict";

  var API = (window.CONFIG && CONFIG.licenseApi)
    ? String(CONFIG.licenseApi).replace(/\/request\/?$/, "")
    : "https://cxpaper-license.chris-73e.workers.dev";

  var DAY = 86400;
  // Identity colours, in fixed order, from the site's own tokens. Blue and
  // olive stay apart for red/green colour blindness, which amber and olive
  // would not. They are never reassigned by a filter.
  var ASKED = "#2757B6";
  var STARTED = "#637F08";
  var INK = "#161311";
  var MUTED = "rgba(22,19,17,0.62)";
  var RULE = "rgba(22,19,17,0.14)";

  var state = { days: 30, data: null, reports: null };

  function $(s, r) { return (r || document).querySelector(s); }
  function el(t, a, kids) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", t);
    for (var k in (a || {})) n.setAttribute(k, a[k]);
    (kids || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function dayKey(epoch) {
    var d = new Date(epoch * 1000);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
           "-" + String(d.getDate()).padStart(2, "0");
  }
  function shortDay(key) {
    var p = key.split("-");
    return p[1].replace(/^0/, "") + "/" + p[2].replace(/^0/, "");
  }
  function ago(epoch) {
    if (!epoch) return "—";
    var d = Math.floor((Date.now() / 1000 - epoch) / DAY);
    if (d <= 0) return "today";
    if (d === 1) return "yesterday";
    if (d < 30) return d + " days ago";
    if (d < 60) return "a month ago";
    return Math.round(d / 30) + " months ago";
  }

  /* ---- the tooltip ------------------------------------------------------ */

  var tip = $("#tip");
  function showTip(x, y, html) {
    tip.innerHTML = html;
    tip.classList.add("show");
    var b = tip.getBoundingClientRect();
    var left = Math.min(x + 14, window.innerWidth - b.width - 8);
    var top = Math.max(8, y - b.height - 12);
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function hideTip() { tip.classList.remove("show"); }

  /* ---- the two lines ---------------------------------------------------- */

  function buckets(claims, days) {
    var now = Math.floor(Date.now() / 1000);
    var from = days ? now - days * DAY : null;
    var keys = [], seen = {};
    function bump(map, epoch) {
      if (!epoch) return;
      if (from && epoch < from) return;
      var k = dayKey(epoch);
      if (!seen[k]) { seen[k] = true; keys.push(k); }
      map[k] = (map[k] || 0) + 1;
    }
    // BOTH series are counted on the day the key was ASKED FOR, never on the
    // day it was opened. A key requested on the 3rd and first opened on the
    // 11th used to land in two different buckets, which made the gap between
    // the lines meaningless - and the figure's caption promises that gap is
    // "people who asked and never opened the program". Counted this way the
    // promise is true: for any day, `asked` is the keys handed out that day
    // and `started` is how many of those same keys have since been opened, so
    // the space between them is exactly the keys still sitting in an inbox.
    var asked = {}, started = {};
    claims.forEach(function (c) {
      bump(asked, c.issued_at);
      if (c.activated_at) bump(started, c.issued_at);
    });
    // Every day in the window, not only days something happened - a line that
    // skips empty days makes a quiet fortnight look like a busy one.
    if (days) {
      keys = [];
      for (var i = days - 1; i >= 0; i--) keys.push(dayKey(now - i * DAY));
    } else {
      keys.sort();
    }
    return keys.map(function (k) {
      return { key: k, asked: asked[k] || 0, started: started[k] || 0 };
    });
  }

  function drawLines(rows) {
    var host = $("#plot-time");
    host.innerHTML = "";
    if (!rows.length) { host.innerHTML = "<p class='why'>Nothing in this window yet.</p>"; return; }

    var W = Math.max(560, Math.min(980, rows.length * 26));
    var H = 260, L = 38, R = 72, T = 16, B = 34;
    var iw = W - L - R, ih = H - T - B;
    var max = Math.max(1, rows.reduce(function (m, r) {
      return Math.max(m, r.asked, r.started); }, 0));
    var ticks = max <= 4 ? max : 4;

    var x = function (i) { return L + (rows.length === 1 ? iw / 2 : i * iw / (rows.length - 1)); };
    var y = function (v) { return T + ih - (v / max) * ih; };

    var svg = el("svg", {
      viewBox: "0 0 " + W + " " + H, width: W, height: H,
      role: "img", "aria-label": "License requests and activations per day"
    });

    for (var t = 0; t <= ticks; t++) {
      var v = Math.round(max * t / ticks), yy = y(v);
      svg.appendChild(el("line", { x1: L, x2: L + iw, y1: yy, y2: yy,
        stroke: RULE, "stroke-width": 1 }));
      var lab = el("text", { x: L - 8, y: yy + 4, "text-anchor": "end",
        fill: MUTED, "font-size": 11, "font-family": "IBM Plex Mono, monospace" });
      lab.textContent = v;
      svg.appendChild(lab);
    }

    var step = Math.max(1, Math.ceil(rows.length / 10));
    rows.forEach(function (r, i) {
      if (i % step && i !== rows.length - 1) return;
      var lab = el("text", { x: x(i), y: H - 10, "text-anchor": "middle",
        fill: MUTED, "font-size": 11, "font-family": "IBM Plex Mono, monospace" });
      lab.textContent = shortDay(r.key);
      svg.appendChild(lab);
    });

    function path(field, colour) {
      var d = rows.map(function (r, i) {
        return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(r[field]).toFixed(1);
      }).join(" ");
      svg.appendChild(el("path", { d: d, fill: "none", stroke: colour,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      // Only points that carry something get a marker; a dot on every zero is
      // noise pretending to be data.
      rows.forEach(function (r, i) {
        if (!r[field]) return;
        svg.appendChild(el("circle", { cx: x(i), cy: y(r[field]), r: 4.5,
          fill: colour, stroke: "#F5F1E8", "stroke-width": 2 }));
      });
      var last = rows[rows.length - 1];
      var lab = el("text", { x: L + iw + 8, y: y(last[field]) + 4, fill: colour,
        "font-size": 12, "font-family": "IBM Plex Mono, monospace" });
      lab.textContent = last[field];
      svg.appendChild(lab);
    }
    path("asked", ASKED);
    path("started", STARTED);

    var cross = el("line", { y1: T, y2: T + ih, stroke: INK, "stroke-width": 1,
      opacity: 0, "stroke-dasharray": "3 3" });
    svg.appendChild(cross);

    var hit = el("rect", { x: L, y: T, width: iw, height: ih, fill: "transparent" });
    svg.appendChild(hit);
    hit.addEventListener("mousemove", function (e) {
      var box = svg.getBoundingClientRect();
      var px = (e.clientX - box.left) * (W / box.width);
      var i = Math.round((px - L) / (iw / Math.max(1, rows.length - 1)));
      i = Math.max(0, Math.min(rows.length - 1, i));
      var r = rows[i];
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      cross.setAttribute("opacity", 0.35);
      showTip(e.clientX, e.clientY,
        "<b>" + esc(r.key) + "</b>" +
        "asked: " + r.asked + "<br>started: " + r.started);
    });
    hit.addEventListener("mouseleave", function () {
      cross.setAttribute("opacity", 0); hideTip();
    });

    host.appendChild(svg);

    var t2 = ["<table class='roster'><tr><th>Day</th><th>Asked</th><th>Started</th></tr>"];
    rows.forEach(function (r) {
      if (!r.asked && !r.started) return;
      t2.push("<tr><td class='mono'>" + esc(r.key) + "</td><td class='mono'>" +
        r.asked + "</td><td class='mono'>" + r.started + "</td></tr>");
    });
    t2.push("</table>");
    $("#table-time").innerHTML = t2.join("");
  }

  /* ---- which tools ------------------------------------------------------ */

  function drawTools(tools) {
    var rows = Object.keys(tools).map(function (k) { return { name: k, n: tools[k] }; })
      .sort(function (a, b) { return b.n - a.n; });
    if (!rows.length) return false;

    var host = $("#plot-tools");
    host.innerHTML = "";
    var W = 640, rowH = 30, L = 150, R = 56;
    var H = rows.length * rowH + 12;
    var iw = W - L - R;
    var max = Math.max.apply(null, rows.map(function (r) { return r.n; }));

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H,
      role: "img", "aria-label": "How often each tool was used" });

    rows.forEach(function (r, i) {
      var y = i * rowH + 6, h = rowH - 12;
      var w = Math.max(2, (r.n / max) * iw);
      var name = el("text", { x: L - 10, y: y + h / 2 + 4, "text-anchor": "end",
        fill: INK, "font-size": 13 });
      name.textContent = r.name;
      svg.appendChild(name);
      var bar = el("rect", { x: L, y: y, width: w, height: h, rx: 4, ry: 4,
        fill: ASKED });
      svg.appendChild(bar);
      var n = el("text", { x: L + w + 8, y: y + h / 2 + 4, fill: MUTED,
        "font-size": 12, "font-family": "IBM Plex Mono, monospace" });
      n.textContent = r.n.toLocaleString();
      svg.appendChild(n);
      bar.addEventListener("mousemove", function (e) {
        showTip(e.clientX, e.clientY, "<b>" + esc(r.name) + "</b>" +
          r.n.toLocaleString() + " times");
      });
      bar.addEventListener("mouseleave", hideTip);
    });
    host.appendChild(svg);

    var t = ["<table class='roster'><tr><th>Tool</th><th>Times used</th></tr>"];
    rows.forEach(function (r) {
      t.push("<tr><td>" + esc(r.name) + "</td><td class='mono'>" + r.n + "</td></tr>");
    });
    t.push("</table>");
    $("#table-tools").innerHTML = t.join("");
    return true;
  }

  /* ---- the reading ------------------------------------------------------ */

  function reading(data, rows) {
    var claims = data.claims || [];
    var now = Math.floor(Date.now() / 1000);
    var lines = [];

    var win = state.days ? state.days : 3650;
    var since = now - win * DAY;
    var askedIn = claims.filter(function (c) { return c.issued_at >= since; });
    var startedIn = claims.filter(function (c) { return c.activated_at && c.activated_at >= since; });
    var period = state.days ? ("the last " + state.days + " days") : "all time";

    if (!claims.length) {
      lines.push("Nobody has asked for a license yet.");
    } else {
      lines.push("<strong>" + askedIn.length + "</strong> " +
        (askedIn.length === 1 ? "person has" : "people have") +
        " asked for a license in " + period + ", and <strong>" +
        startedIn.length + "</strong> started the program.");
    }

    // The one number worth acting on: asked days ago, never opened it.
    var stale = claims.filter(function (c) {
      return !c.activated_at && c.issued_at < now - 7 * DAY;
    });
    if (stale.length) {
      lines.push("<strong>" + stale.length + "</strong> " +
        (stale.length === 1 ? "person asked" : "people asked") +
        " more than a week ago and never opened it. " +
        (stale.length === 1 ? "That is" : "Those are") +
        " worth a phone call — either it did not arrive or they got stuck.");
    }

    var projects = {};
    claims.forEach(function (c) {
      var p = (c.project || "").trim();
      if (p) projects[p] = (projects[p] || 0) + 1;
    });
    var top = Object.keys(projects).sort(function (a, b) { return projects[b] - projects[a]; });
    if (top.length > 1) {
      lines.push("They are on " + top.length + " different projects. The most of them, " +
        projects[top[0]] + ", are on <strong>" + esc(top[0]) + "</strong>.");
    }

    if (!state.reports) {
      lines.push("No copy has reported its usage yet, so there is nothing to say " +
        "about which tools are earning their place.");
    }

    $("#reading-body").innerHTML = lines.map(function (l) { return "<p>" + l + "</p>"; }).join("");
    $("#reading").hidden = false;
  }

  /* ---- drawing the whole page ------------------------------------------- */

  function tiles(data) {
    var claims = data.claims || [];
    var activated = claims.filter(function (c) { return c.machine; }).length;
    var waiting = claims.length - activated;
    var set = [
      { n: data.keys_in_stock, k: "keys in stock",
        sub: data.keys_in_stock < 20 ? "Running low" : "" },
      { n: claims.length, k: "licenses issued", sub: "" },
      { n: activated, k: "in use", sub: "opened on a computer" },
      { n: waiting, k: "never opened", sub: waiting ? "asked, but has not started it" : "" }
    ];
    $("#tiles").innerHTML = set.map(function (t) {
      return "<div class='tile'><span class='n'>" + (t.n == null ? "—" : t.n) +
        "</span><span class='k'>" + esc(t.k) + "</span>" +
        (t.sub ? "<p class='sub'>" + esc(t.sub) + "</p>" : "") + "</div>";
    }).join("");

    var b = [];
    if (data.keys_in_stock != null && data.keys_in_stock < 20) {
      b.push("<div class='banner" + (data.keys_in_stock === 0 ? " bad" : "") + "'><p>" +
        (data.keys_in_stock === 0
          ? "<strong>No keys left.</strong> The form is turning people away. Run mint_batch.py to put more in."
          : "<strong>" + data.keys_in_stock + " keys left.</strong> Run mint_batch.py before it runs out.") +
        "</p></div>");
    }
    $("#banners").innerHTML = b.join("");
  }

  function roster(data) {
    var claims = (data.claims || []).slice().sort(function (a, b) {
      return (b.issued_at || 0) - (a.issued_at || 0); });
    // The Key column is not decoration. tools/revoked.txt takes the license
    // id and nothing else, so without this column switching off one license
    // meant opening dev-tools to find the id that was already on the screen's
    // own data. Click it to copy.
    var out = ["<tr><th>Key</th><th>Name</th><th>Project</th><th>Phone</th><th>Email</th>" +
               "<th>Asked</th><th>Started</th><th>Last heard</th><th>Computer</th></tr>"];
    if (!claims.length) {
      out.push("<tr><td colspan='9'>Nobody yet.</td></tr>");
    }
    claims.forEach(function (c) {
      out.push("<tr>" +
        "<td><button type='button' class='keyid' data-id='" + esc(c.id || "") +
          "' title='Copy this key id'>" + esc(c.id || "—") + "</button></td>" +
        "<td>" + esc(c.name || "—") + "</td>" +
        "<td>" + esc(c.project || "—") + "</td>" +
        "<td class='mono'>" + esc(c.phone || "—") + "</td>" +
        "<td class='mono'>" + esc(c.email || "—") + "</td>" +
        "<td>" + esc(ago(c.issued_at)) + "</td>" +
        "<td>" + (c.machine
          ? "<span class='pill on'>" + esc(ago(c.activated_at)) + "</span>"
          : "<span class='pill off'>not yet</span>") + "</td>" +
        "<td>" + (c.last_report_at
          ? esc(ago(c.last_report_at))
          : "<span class='pill off'>never</span>") + "</td>" +
        "<td class='mono'>" + esc(c.machine || "—") + "</td>" +
        "</tr>");
    });
    $("#roster").innerHTML = out.join("");
  }

  // One click puts the id on the clipboard, because the next thing it does is
  // get pasted into tools\revoked.txt.
  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("button.keyid") : null;
    if (!b) return;
    var id = b.getAttribute("data-id") || "";
    if (!id) return;
    var said = function (word) {
      var was = b.textContent;
      b.textContent = word;
      setTimeout(function () { b.textContent = was; }, 900);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(id).then(function () { said("copied"); },
                                             function () { said(id); });
    } else {
      said(id);
    }
  });

  function render() {
    var data = state.data;
    if (!data) return;
    tiles(data);
    var rows = buckets(data.claims || [], state.days);
    drawLines(rows);
    roster(data);
    reading(data, rows);
    if (state.reports && state.reports.tools && drawTools(state.reports.tools)) {
      $("#fig-tools").hidden = false;
    }
  }

  /* ---- getting in ------------------------------------------------------- */

  function load(password) {
    var state$ = $("#desk-state");
    state$.textContent = "Opening...";
    state$.className = "form-state";

    return fetch(API + "/admin/data", { headers: { "X-CP-Admin": password } })
      .then(function (r) {
        if (r.status === 401) throw new Error("That password was not accepted.");
        if (!r.ok) throw new Error("The license desk answered " + r.status + ".");
        return r.json();
      })
      .then(function (doc) {
        state.data = doc;
        try { sessionStorage.setItem("cp-desk", password); } catch (e) { /* private window */ }
        return fetch(API + "/admin/reports", { headers: { "X-CP-Admin": password } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; });
      })
      .then(function (reports) {
        state.reports = reports;
        $("#desk-gate").hidden = true;
        $("#desk").hidden = false;
        render();
      })
      .catch(function (err) {
        state$.textContent = err.message || "That did not work.";
        state$.className = "form-state bad";
      });
  }

  $("#desk-gate").addEventListener("submit", function (e) {
    e.preventDefault();
    var pw = $("#desk-pw").value.trim();
    if (!pw) { $("#desk-state").textContent = "Type the password."; return; }
    load(pw);
  });

  Array.prototype.forEach.call($("#range").children, function (b) {
    b.addEventListener("click", function () {
      Array.prototype.forEach.call($("#range").children, function (o) {
        o.setAttribute("aria-pressed", String(o === b));
      });
      state.days = parseInt(b.getAttribute("data-days"), 10);
      render();
    });
  });

  try {
    var saved = sessionStorage.getItem("cp-desk");
    if (saved) { $("#desk-pw").value = saved; load(saved); }
  } catch (e) { /* nothing */ }
})();
