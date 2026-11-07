// Debug page: calls the portal's own /api/* (the server talks to the NBI) and follows /events.
(function () {
  "use strict";
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  var exchangesEl = document.getElementById("exchanges");
  var summary = document.getElementById("summary");
  var logEl = document.getElementById("log");
  var sseState = document.getElementById("sse-state");

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function pretty(obj) { return JSON.stringify(obj, null, 2); }

  function renderExchange(title, ex) {
    var box = el("article", "exchange");
    if (!ex) { return box; }
    var code = ex.code === null || ex.code === undefined ? "-" : String(ex.code);
    var head = el("h3", null, title + ": " + ex.request_type + " → " + (ex.host || "(not sent)"));
    var badge = el("span", "badge " + (ex.error ? "bad" : (ex.code === 101 || ex.code === 201 || ex.code === 200 ? "ok" : "warn")),
      ex.error ? ex.error.kind : code + " " + (ex.code_meaning || ""));
    head.appendChild(document.createTextNode(" "));
    head.appendChild(badge);
    box.appendChild(head);
    var meta = el("p", "meta", (ex.url || "") + "  |  " + ex.duration_ms + " ms" +
      (ex.tls && ex.tls.version ? "  |  " + ex.tls.version + " " + ex.tls.cipher : "") +
      (ex.http_status ? "  |  HTTP " + ex.http_status : ""));
    box.appendChild(meta);
    var cols = el("div", "cols");
    var req = el("div"); req.appendChild(el("h4", null, "Request (secrets masked)"));
    req.appendChild(el("pre", null, pretty(ex.request)));
    var rep = el("div"); rep.appendChild(el("h4", null, "Reply"));
    rep.appendChild(el("pre", null, ex.error ? pretty(ex.error) : pretty(ex.reply)));
    cols.appendChild(req); cols.appendChild(rep);
    box.appendChild(cols);
    if (ex.tls && ex.tls.cert_sha256) {
      box.appendChild(el("p", "meta", "Server cert SHA-256 " + ex.tls.cert_sha256 + " (verified as " + ex.tls.server_name + ")"));
    }
    return box;
  }

  function post(action) {
    summary.textContent = "Calling " + action + "…";
    var t0 = performance.now();
    return fetch("/api/" + action, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" },
      body: "{}"
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      var ms = Math.round(performance.now() - t0);
      var d = res.data;
      exchangesEl.textContent = "";
      if (res.status !== 200) {
        summary.textContent = action + " failed: HTTP " + res.status + " " + (d.error || "");
        return;
      }
      if (action === "accept") {
        summary.textContent = (d.ok ? "AUTHORIZED" : "NOT AUTHORIZED (" + d.outcome + ")") +
          ": NBI " + (d.code === null ? "-" : d.code) + " " + (d.message || "") +
          " | server " + d.total_ms + " ms, browser round trip " + ms + " ms";
        if (d.status_before) { exchangesEl.appendChild(renderExchange("Status before", d.status_before)); }
        (d.exchanges || []).forEach(function (ex, i) { exchangesEl.appendChild(renderExchange("Call " + (i + 1), ex)); });
        if (d.status_after) { exchangesEl.appendChild(renderExchange("Status after", d.status_after)); }
        if (d.redirect_target) {
          var p = el("p", "meta", "Customer mode would now redirect to: ");
          var a = el("a", null, d.redirect_target); a.href = d.redirect_target; a.rel = "noreferrer";
          p.appendChild(a); exchangesEl.appendChild(p);
        }
      } else if (action === "decrypt") {
        summary.textContent = "Decrypt done (" + ms + " ms)";
        Object.keys(d.decrypt || {}).forEach(function (k) { exchangesEl.appendChild(renderExchange(k, d.decrypt[k])); });
        if (!Object.keys(d.decrypt || {}).length) { summary.textContent = "Nothing to decrypt: client_mac/uip are not ENC values"; }
      } else {
        var ex = d.exchange;
        summary.textContent = action + ": " + (ex.error ? ex.error.kind + " " + ex.error.detail : ex.code + " " + ex.code_meaning) +
          " (" + ex.duration_ms + " ms)";
        exchangesEl.appendChild(renderExchange(action, ex));
      }
    }).catch(function (err) {
      summary.textContent = action + " failed: " + err;
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("button[data-action]"), function (b) {
    b.addEventListener("click", function () {
      if (b.dataset.action === "logout" || b.dataset.action === "disconnect") {
        if (!window.confirm(b.dataset.action + " this client on the controller?")) { return; }
      }
      b.disabled = true;
      post(b.dataset.action).then(function () { b.disabled = false; });
    });
  });

  // Live step log for this visit only (server filters by the session's reference).
  if (window.EventSource) {
    var es = new EventSource("/events?ref=self");
    es.addEventListener("open", function () { sseState.textContent = "live"; });
    es.addEventListener("error", function () { sseState.textContent = "reconnecting"; });
    es.addEventListener("step", function (msg) {
      var ev; try { ev = JSON.parse(msg.data); } catch (e) { return; }
      var li = el("li", "ev ev-" + ev.event);
      li.appendChild(el("time", null, ev.ts.substring(11)));
      li.appendChild(el("strong", null, ev.event));
      var bits = [];
      ["request_type", "nbi_host", "ResponseCode", "ReplyMessage", "duration_ms", "outcome", "total_ms", "error_kind", "error", "target"].forEach(function (k) {
        if (ev[k] !== undefined && ev[k] !== null && ev[k] !== "") { bits.push(k + "=" + ev[k]); }
      });
      li.appendChild(el("span", null, bits.join("  ")));
      logEl.appendChild(li);
      li.scrollIntoView({ block: "nearest" });
    });
  } else {
    sseState.textContent = "unsupported";
  }
})();
