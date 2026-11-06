"""WISPr external captive portal (click-through) for RUCKUS SmartZone and RUCKUS One.

The browser never talks to the controller: on "I agree" this server calls the
controller's WISPr northbound interface (NBI) itself. Backend, mode, NBI hosts and
credentials come from the environment (see README.md); nothing secret reaches the page.
"""

from __future__ import annotations

import json
import os
import queue
import time
from datetime import timedelta

from flask import (Flask, Response, abort, g, jsonify, render_template, request,
                   send_file, session, stream_with_context)
from werkzeug.middleware.proxy_fix import ProxyFix

from wispr import __version__
from wispr.config import Config, load_config
from wispr.events import EventBus
from wispr.flow import FRIENDLY, Authorizer
from wispr.masking import mask_body, mask_ip, mask_mac, mask_params
from wispr.nbi import REPLY_CODES, NbiClient
from wispr.params import KNOWN, RedirectParams, parse_redirect, safe_http_url
from wispr.security import RateLimiter, apply_headers, csrf_ok, new_csrf, new_ref

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class _Params:
    """Adapter so the stored (already validated) values behave like RedirectParams."""

    def __init__(self, values: dict):
        self.values = values

    def get(self, name, default=""):
        return self.values.get(name, default)


def _paragraphs(text: str) -> list[dict]:
    """Plain text -> blocks. '# ' starts a heading, '- ' a list item, blank line = new paragraph."""
    blocks, para, items = [], [], []

    def flush():
        if para:
            blocks.append({"type": "p", "text": " ".join(para)})
            para.clear()
        if items:
            blocks.append({"type": "ul", "items": list(items)})
            items.clear()

    for line in text.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("# "):
            flush()
            blocks.append({"type": "h", "text": s[2:].strip()})
        elif s.startswith("- "):
            if para:
                blocks.append({"type": "p", "text": " ".join(para)})
                para.clear()
            items.append(s[2:].strip())
        else:
            if items:
                flush()
            para.append(s)
    flush()
    return blocks


def _load_text(path: str) -> str:
    with open(os.path.join(BASE_DIR, "content", path), "r", encoding="utf-8") as fh:
        return fh.read()


def create_app(cfg: Config | None = None) -> Flask:
    cfg = cfg or load_config()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    if cfg.trust_proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=cfg.trust_proxy_hops,
                                x_proto=cfg.trust_proxy_hops, x_host=cfg.trust_proxy_hops)

    tls_enabled = bool(os.environ.get("TLS_CERT_FILE"))
    cookie_secure = os.environ.get("COOKIE_SECURE", "1" if tls_enabled else "0").lower() in ("1", "true", "yes")
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        SESSION_COOKIE_NAME="wp_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=cfg.session_ttl_s),
        MAX_CONTENT_LENGTH=16 * 1024,
        JSON_SORT_KEYS=False,
    )

    bus = EventBus(cfg.log_json_path, cfg.log_console)
    client = NbiClient(cfg.nbi)
    mask_public = not cfg.is_debug
    auth = Authorizer(client, bus, mask_public=mask_public, backend=cfg.nbi.backend)
    limiter = RateLimiter()
    terms_blocks = _paragraphs(cfg.terms_text or _load_text("terms.txt"))
    notice_blocks = _paragraphs(cfg.notice_text or _load_text("dod-notice.txt"))

    app.extensions["wispr"] = {"cfg": cfg, "bus": bus, "client": client, "auth": auth}

    bus.emit("startup", {
        "version": __version__, "mode": cfg.mode, "backend": cfg.nbi.backend,
        "nbi_hosts": list(cfg.nbi.hosts), "nbi_port": cfg.nbi.port,
        "auth_method": cfg.nbi.auth_method, "ca_bundle": cfg.nbi.ca_bundle,
        "tls_server_name": cfg.nbi.tls_server_name, "cert_pinned": bool(cfg.nbi.cert_sha256),
        "secret_key_generated": cfg.secret_key_generated,
    })

    # ---- helpers ----------------------------------------------------------------------
    def client_ip() -> str:
        return request.remote_addr or "unknown"

    def pub_client(ip: str) -> str:
        return mask_ip(ip) if mask_public else ip

    def emit(event: str, **data):
        """Log with full values; publish masked values in customer mode."""
        full = {"ref": g.get("ref"), "mode": cfg.mode, "client": client_ip(), **data}
        public = dict(full)
        public["client"] = pub_client(client_ip())
        if mask_public:
            if "params" in public:
                public["params"] = mask_params(public["params"], True)
            for k in ("client_mac",):
                if k in public and public[k]:
                    public[k] = mask_mac(public[k])
            if "uip" in public and public["uip"]:
                public["uip"] = mask_ip(public["uip"])
        return bus.emit(event, full, public)

    def brand_ctx() -> dict:
        return {
            "facility": cfg.facility_name,
            "logo_url": "/brand/logo" if cfg.logo_path else None,
            "logo_alt": cfg.logo_alt or f"{cfg.facility_name} logo",
            "help_text": cfg.help_text,
        }

    def error_page(kind: str, status: int, retry_url: str | None = None):
        title, body = FRIENDLY[kind]
        emit("error_shown", kind=kind, http_status=status)
        return render_template("customer/error.html", title=title, body=body,
                               ref=g.get("ref") or new_ref(), retry_url=retry_url,
                               **brand_ctx()), status

    def redirect_target(values: dict) -> str | None:
        for key in (("startUrl", "url") if cfg.use_start_url else ("url",)):
            url = safe_http_url(values.get(key, ""))
            if url:
                return url
        return cfg.default_redirect_url or None

    def stored_visit() -> dict | None:
        visit = session.get("visit")
        if not isinstance(visit, dict):
            return None
        if time.time() - float(visit.get("created", 0)) > cfg.session_ttl_s:
            return None
        return visit

    # ---- per-request hooks ------------------------------------------------------------
    @app.before_request
    def _start():
        g.t0 = time.perf_counter()
        g.ref = None
        visit = session.get("visit")
        if isinstance(visit, dict):
            g.ref = visit.get("ref")

    @app.after_request
    def _headers(resp):
        static = request.path.startswith("/static/") or request.path == "/brand/logo"
        apply_headers(resp, is_https=request.is_secure, static=static)
        resp.headers["X-Request-Ref"] = g.get("ref") or ""
        return resp

    @app.errorhandler(404)
    def _404(_e):
        if request.path.startswith("/api/") or request.path in ("/events",):
            return jsonify(error="not found"), 404
        return render_template("customer/error.html", title="Page not found",
                               body="Please open any web page to get back to the guest Wi-Fi sign-in.",
                               ref=g.get("ref") or new_ref(), retry_url=None, **brand_ctx()), 404

    @app.errorhandler(413)
    def _413(_e):
        return jsonify(error="request too large"), 413

    @app.errorhandler(500)
    def _500(_e):
        ref = g.get("ref") or new_ref()
        bus.emit("server_error", {"ref": ref, "path": request.path}, {"ref": ref})
        return render_template("customer/error.html", title="Something went wrong",
                               body="Please try again in a few minutes.", ref=ref,
                               retry_url=None, **brand_ctx()), 500

    # ---- routes -----------------------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=__version__, mode=cfg.mode, backend=cfg.nbi.backend,
                       nbi_hosts=len(cfg.nbi.hosts))

    @app.get("/brand/logo")
    def logo():
        if not cfg.logo_path:
            abort(404)
        return send_file(cfg.logo_path, max_age=3600)

    @app.get("/")
    def landing():
        if not limiter.allow("page", client_ip(), cfg.rate_page_per_min):
            g.ref = g.ref or new_ref()
            emit("rate_limited", bucket="page")
            return error_page("rate_limited", 429)

        params: RedirectParams = parse_redirect(request.args)
        g.ref = new_ref()
        emit("redirect_received", params=params.values, unknown=params.unknown,
             rejected=params.rejected, missing=params.missing, aliases=params.aliases,
             user_agent=request.headers.get("User-Agent", "")[:300])

        if not params.ok:
            emit("params_invalid", rejected=params.rejected, missing=params.missing)
            if not cfg.is_debug:
                session.pop("visit", None)
                return error_page("bad_params", 400)

        csrf = new_csrf()
        session.clear()
        session.permanent = True
        session["visit"] = {"ref": g.ref, "csrf": csrf, "params": params.values,
                            "created": time.time(), "query": request.query_string.decode("latin-1")[:4096]}

        if cfg.is_debug:
            emit("debug_shown")
            return render_template("debug.html", **debug_ctx(params, csrf, g.ref))

        emit("terms_shown", facility=cfg.facility_name)
        return render_template("customer/terms.html", csrf=csrf, ref=g.ref,
                               welcome=cfg.welcome_text, terms=terms_blocks, notice=notice_blocks,
                               agree_label=cfg.agree_label, **brand_ctx())

    def debug_ctx(params: RedirectParams, csrf: str, ref: str) -> dict:
        n = cfg.nbi
        rows = []
        for name, (_v, desc) in KNOWN.items():
            if name in params.values:
                rows.append({"name": name, "value": params.values[name], "desc": desc, "state": "ok"})
            elif name in params.rejected:
                raw = request.args.get(name, "")[:200]
                rows.append({"name": name, "value": raw, "desc": desc, "state": params.rejected[name]})
            elif name in params.missing:
                rows.append({"name": name, "value": "", "desc": desc, "state": "missing (required)"})
        for name, val in params.unknown.items():
            rows.append({"name": name, "value": val, "desc": "not used by the portal", "state": "unknown"})
        try:
            hosts = client.hosts_for(params.get("nbiIP") or None)
            nbi_note = f"will call {hosts[0]}" + (f" (fallback: {', '.join(hosts[1:])})" if hosts[1:] else "")
        except Exception as exc:   # HostNotAllowed
            nbi_note = str(exc)
        return {
            "ref": ref, "csrf": csrf, "rows": rows, "params_ok": params.ok,
            "mac_encrypted": params.mac_encrypted, "nbi_note": nbi_note,
            "settings": [
                ("Backend", n.backend), ("Mode", cfg.mode), ("NBI allowlist", ", ".join(n.hosts)),
                ("NBI port / path", f"{n.port} {n.path}"), ("Auth method", n.auth_method),
                ("NBI user", n.request_username or "(none)"), ("NBI password", "configured (hidden)"),
                ("Guest UE-Username", n.guest_username if n.auth_method != "authorize" else "(not sent)"),
                ("CA bundle", n.ca_bundle or "system trust store"),
                ("TLS server name", n.tls_server_name or "(the NBI host)"),
                ("Pinned cert SHA-256", n.cert_sha256 or "(none)"),
                ("TLS", f"1.2+ ECDHE AES-GCM" + (", max 1.2" if n.tls_max_version == "1.2" else "")),
                ("Status supported", str(n.status_supported)),
            ],
            "redirect_target": redirect_target(params.values) or "(none: success page only)",
            "query": request.query_string.decode("latin-1"),
        }

    def check_post(json_api: bool):
        """Common checks for the accept/debug POSTs. Returns (visit, error_response)."""
        if not limiter.allow("accept", client_ip(), cfg.rate_accept_per_min):
            emit("rate_limited", bucket="accept")
            return None, (jsonify(error="rate_limited", ref=g.ref), 429) if json_api else error_page("rate_limited", 429)
        visit = stored_visit()
        given = request.headers.get("X-CSRF-Token") if json_api else request.form.get("csrf")
        if visit is None or not csrf_ok(visit.get("csrf"), given):
            emit("csrf_failed", has_session=visit is not None)
            return None, (jsonify(error="expired", ref=g.ref), 403) if json_api else error_page("expired", 403)
        return visit, None

    @app.post("/accept")
    def accept():
        visit, err = check_post(json_api=False)
        if err:
            return err
        params = _Params(visit["params"])
        emit("accept_received", via="form")
        outcome = auth.accept(g.ref, params, status_checks=False)
        if cfg.log_decrypt_ue and cfg.nbi.backend == "smartzone" and params.get("client_mac", "").startswith("ENC"):
            clear = auth.decrypt(g.ref, params, params.get("client_mac"))
            bus.emit("ue_decrypted", {"ref": g.ref, "client_mac_clear": clear}, {"ref": g.ref})
        if not outcome.ok:
            return error_page(outcome.kind, 502, retry_url="/?" + visit.get("query", ""))
        target = redirect_target(visit["params"])
        emit("success_shown", outcome_ms=outcome.total_ms)
        if target:
            emit("redirect_issued", target=target, delay_s=cfg.redirect_delay_s)
        session.pop("visit", None)
        return render_template("customer/success.html", target=target, delay=cfg.redirect_delay_s,
                               ref=g.ref, **brand_ctx())

    # ---- debug JSON API ---------------------------------------------------------------
    def debug_only():
        if not cfg.is_debug:
            abort(404)

    def exchange_json(ex) -> dict | None:
        if ex is None:
            return None
        return {
            "request_type": ex.request_type, "host": ex.host, "url": ex.url,
            "request": mask_body(ex.body, mask_ue=False), "http_status": ex.http_status,
            "reply": ex.reply, "code": ex.code,
            "code_meaning": REPLY_CODES.get(ex.code, "") if ex.code is not None else "",
            "duration_ms": ex.duration_ms, "tls": ex.tls,
            "error": None if ex.error is None else {"kind": ex.error.kind, "detail": ex.error.detail},
        }

    @app.post("/api/accept")
    def api_accept():
        debug_only()
        visit, err = check_post(json_api=True)
        if err:
            return err
        params = _Params(visit["params"])
        emit("accept_received", via="debug")
        outcome = auth.accept(g.ref, params, status_checks=cfg.debug_status_checks)
        target = redirect_target(visit["params"]) if outcome.ok else None
        if target:
            emit("redirect_issued", target=target, delay_s=None, note="debug mode: link only")
        return jsonify(ref=g.ref, outcome=outcome.kind, ok=outcome.ok, code=outcome.code,
                       message=outcome.message, total_ms=outcome.total_ms,
                       friendly=None if outcome.ok else FRIENDLY.get(outcome.kind),
                       status_before=exchange_json(outcome.status_before),
                       exchanges=[exchange_json(e) for e in outcome.exchanges],
                       status_after=exchange_json(outcome.status_after),
                       redirect_target=target)

    @app.post("/api/<action>")
    def api_action(action):
        debug_only()
        if action not in ("status", "logout", "disconnect", "decrypt"):
            abort(404)
        visit, err = check_post(json_api=True)
        if err:
            return err
        params = _Params(visit["params"])
        emit("debug_action", action=action)
        if action == "decrypt":
            if cfg.nbi.backend != "smartzone" or not cfg.debug_decrypt:
                return jsonify(error="decrypt is only offered for the SmartZone backend with DEBUG_DECRYPT on"), 400
            results = {}
            for key in ("client_mac", "uip"):
                if params.get(key, "").startswith("ENC"):
                    ex = auth.call(g.ref, "decrypt", params, data=params.get(key))
                    results[key] = exchange_json(ex)
            return jsonify(ref=g.ref, decrypt=results)
        ex = auth.call(g.ref, action, params)
        return jsonify(ref=g.ref, exchange=exchange_json(ex))

    # ---- SSE --------------------------------------------------------------------------
    @app.get("/events")
    def events():
        own = request.args.get("ref") == "self"
        if own:
            visit = session.get("visit")
            if not cfg.is_debug or not isinstance(visit, dict):
                abort(403)
            only_ref = visit.get("ref")
        else:
            token = request.args.get("token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
            if not cfg.events_token or not csrf_ok(cfg.events_token, token):
                abort(403)
            only_ref = None
        q = bus.subscribe()
        if q is None:
            return jsonify(error="too many event subscribers"), 503

        def gen():
            try:
                yield "retry: 3000\n\n"
                last_beat = time.monotonic()
                while True:
                    try:
                        item = q.get(timeout=5)
                    except queue.Empty:
                        item = None
                    if item is not None and (only_ref is None or item.get("ref") == only_ref):
                        yield f"event: step\ndata: {json.dumps(item, default=str)}\n\n"
                    if time.monotonic() - last_beat > 15:
                        last_beat = time.monotonic()
                        yield ": keep-alive\n\n"
            finally:
                bus.unsubscribe(q)

        resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    return app


def _lazy_app():
    return create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    create_app().run(host=os.environ.get("BIND_ADDR", "127.0.0.1"), port=port, threaded=True)
else:
    # gunicorn server:app
    app = _lazy_app() if os.environ.get("WISPR_NO_AUTOAPP") != "1" else None
