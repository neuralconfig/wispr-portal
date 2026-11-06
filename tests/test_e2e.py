"""End-to-end: portal (Flask test client) -> real TLS -> fake NBI, in both modes."""

import json
import re

from conftest import ENC_MAC, redirect_qs


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert m, "no csrf token in page"
    return m.group(1)


def events(app):
    return [json.loads(line) for line in app.log_path.read_text().splitlines() if line.strip()]


# ---- customer mode ------------------------------------------------------------------
def test_customer_click_through(make_app, nbi):
    app = make_app()
    c = app.test_client()
    r = c.get("/", query_string=redirect_qs())
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Demo Medical Center" in html and "I agree" in html
    assert "U.S. Government (USG) Information System" in html
    assert "nbi-secret" not in html and ENC_MAC not in html     # no secrets or UE ids in the page
    assert "<script>" not in html and "style=" not in html       # CSP: no inline script/style
    ref = re.search(r"Reference: <span>([A-Z0-9-]+)</span>", html).group(1)

    r = c.post("/accept", data={"csrf": csrf_from(html)})
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "You are connected" in page
    assert 'http-equiv="refresh" content="4;url=http://connectivitycheck.gstatic.com/generate_204"' in page

    sent = nbi.requests[-1]
    assert sent["RequestType"] == "Login" and sent["UE-MAC"] == ENC_MAC
    assert sent["RequestUserName"] == "nbi" and sent["RequestPassword"] == "nbi-secret"

    ev = events(app)
    names = [e["event"] for e in ev if e.get("ref") == ref]
    for step in ("redirect_received", "terms_shown", "accept_received", "nbi_request",
                 "nbi_response", "auth_result", "success_shown", "redirect_issued"):
        assert step in names, step
    resp = next(e for e in ev if e["event"] == "nbi_response")
    assert resp["ResponseCode"] == 201 and resp["ReplyMessage"] == "Login succeeded"
    assert resp["tls"]["version"] in ("TLSv1.2", "TLSv1.3")
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", resp["ts"])
    req = next(e for e in ev if e["event"] == "nbi_request")
    assert req["body"]["RequestPassword"] == "********"               # never in the log
    assert req["client_mac"] == ENC_MAC                                 # full value in server log


def test_customer_second_accept_is_already_authorized(make_app, nbi):
    c = make_app().test_client()
    for expected in (201, 101):
        html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
        r = c.post("/accept", data={"csrf": csrf_from(html)})
        assert "You are connected" in r.get_data(as_text=True)
    assert [x["RequestType"] for x in nbi.requests] == ["Login", "Login"]


def test_customer_sse_is_masked(make_app, nbi):
    app = make_app(EVENTS_TOKEN="t" * 32)
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    c.post("/accept", data={"csrf": csrf_from(html)})
    bus = app.extensions["wispr"]["bus"]
    pub = json.dumps(bus.history())
    assert ENC_MAC not in pub and "10.7.39.50" not in pub and "nbi-secret" not in pub
    assert c.get("/events").status_code == 403
    assert c.get("/events?token=wrong").status_code == 403
    assert c.get("/events?ref=self").status_code == 403           # own-visit stream is debug only


def test_csrf_required(make_app, nbi):
    c = make_app().test_client()
    c.get("/", query_string=redirect_qs())
    r = c.post("/accept", data={"csrf": "forged"})
    assert r.status_code == 403 and "This page has expired" in r.get_data(as_text=True)
    r = make_app().test_client().post("/accept", data={})
    assert r.status_code == 403
    assert nbi.requests == []


def test_bad_params_friendly_error_with_reference(make_app, nbi):
    app = make_app()
    r = app.test_client().get("/", query_string=redirect_qs(client_mac="zzz"))
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    ref = re.search(r"<strong>([A-Z0-9]{4}-[A-Z0-9]{4})</strong>", html).group(1)
    assert any(e["event"] == "params_invalid" and e["ref"] == ref for e in events(app))


def test_nbiip_outside_allowlist_never_called(make_app, nbi):
    app = make_app()
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs(nbiIP="10.9.9.9")).get_data(as_text=True)
    r = c.post("/accept", data={"csrf": csrf_from(html)})
    assert r.status_code == 502 and "temporarily unavailable" in r.get_data(as_text=True)
    assert nbi.requests == []
    assert any(e["event"] == "nbi_not_allowed" for e in events(app))


def test_wrong_ca_fails_closed(make_app, nbi, pki):
    app = make_app(SZ_CA_BUNDLE=pki["other_ca"])
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    r = c.post("/accept", data={"csrf": csrf_from(html)})
    assert r.status_code == 502
    err = next(e for e in events(app) if e["event"] == "nbi_error")
    assert err["error_kind"] == "tls"
    assert nbi.requests == []


def test_tls_server_name_and_pin(make_app, nbi, pki):
    import hashlib
    import ssl
    der = ssl.PEM_cert_to_DER_cert(open(pki["cert"]).read())
    good = hashlib.sha256(der).hexdigest()
    for pin, ok in ((good, True), ("0" * 64, False)):
        app = make_app(SZ_TLS_SERVER_NAME="scg.ruckuswireless.com", SZ_CERT_SHA256=pin)
        c = app.test_client()
        html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
        r = c.post("/accept", data={"csrf": csrf_from(html)})
        assert (r.status_code == 200) is ok


def test_wrong_nbi_password_is_friendly(make_app, nbi):
    app = make_app(SZ_NBI_PASSWORD="wrong")
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    r = c.post("/accept", data={"csrf": csrf_from(html)})
    page = r.get_data(as_text=True)
    assert r.status_code == 502 and "306" not in page and "temporarily unavailable" in page
    res = next(e for e in events(app) if e["event"] == "auth_result")
    assert res["ResponseCode"] == 306 and res["outcome"] == "portal_config"


def test_unknown_client_not_found(make_app, nbi):
    nbi.unknown_macs.add("aa:bb:cc:dd:ee:01")
    c = make_app().test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    page = c.post("/accept", data={"csrf": csrf_from(html)}).get_data(as_text=True)
    assert "could not find your device" in page and "Try again" in page


def test_rate_limit(make_app, nbi):
    c = make_app(RATE_ACCEPT_PER_MIN=2).test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    token = csrf_from(html)
    codes = [c.post("/accept", data={"csrf": token}).status_code for _ in range(3)]
    assert codes[-1] == 429


def test_security_headers(make_app, nbi):
    c = make_app().test_client()
    r = c.get("/", query_string=redirect_qs())
    h = r.headers
    assert "script-src 'self'" in h["Content-Security-Policy"] and "unsafe-inline" not in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store" and h["X-Frame-Options"] == "DENY"
    assert "Access-Control-Allow-Origin" not in h
    assert "HttpOnly" in h["Set-Cookie"] and "SameSite=Lax" in h["Set-Cookie"]
    r = c.get("/", query_string=redirect_qs(), base_url="https://portal.example")
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")


def test_healthz(make_app, nbi):
    r = make_app().test_client().get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok" and "nbi-secret" not in r.get_data(as_text=True)


def test_debug_api_hidden_in_customer_mode(make_app, nbi):
    c = make_app().test_client()
    c.get("/", query_string=redirect_qs())
    assert c.post("/api/accept").status_code == 404


# ---- debug mode ---------------------------------------------------------------------
def test_debug_mode_full_flow(make_app, nbi):
    app = make_app(PORTAL_MODE="debug")
    c = app.test_client()
    r = c.get("/", query_string=redirect_qs(foo="bar"))
    html = r.get_data(as_text=True)
    assert "Redirect parameters" in html and ENC_MAC in html and "foo" in html
    assert "nbi-secret" not in html and "configured (hidden)" in html
    token = csrf_from(html)

    r = c.post("/api/accept", headers={"X-CSRF-Token": token})
    d = r.json
    assert d["ok"] and d["code"] == 201 and d["total_ms"] >= 0
    assert d["status_before"]["code"] == 304 and d["status_after"]["code"] == 304   # vSZ-H default
    assert d["exchanges"][0]["request"]["RequestPassword"] == "********"
    assert d["exchanges"][0]["request"]["UE-Password"] == "********"
    assert d["exchanges"][0]["tls"]["cert_sha256"]

    nbi.status_supported = True
    s = c.post("/api/status", headers={"X-CSRF-Token": token}).json
    assert s["exchange"]["code"] == 101
    dec = c.post("/api/decrypt", headers={"X-CSRF-Token": token}).json
    assert dec["decrypt"]["client_mac"]["reply"]["Data"] == "AA:BB:CC:DD:EE:01"
    lo = c.post("/api/logout", headers={"X-CSRF-Token": token}).json
    assert lo["exchange"]["code"] == 200
    assert c.post("/api/status", headers={"X-CSRF-Token": "nope"}).status_code == 403


def test_debug_status_before_after_when_supported(make_app, nbi):
    nbi.status_supported = True
    c = make_app(PORTAL_MODE="debug").test_client()
    token = csrf_from(c.get("/", query_string=redirect_qs()).get_data(as_text=True))
    d = c.post("/api/accept", headers={"X-CSRF-Token": token}).json
    assert d["status_before"]["code"] == 100 and d["status_after"]["code"] == 101


def test_login_async_polls_status(make_app, nbi):
    nbi.status_supported = True
    nbi.async_steps = 2
    app = make_app(SZ_AUTH_METHOD="login_async", SZ_STATUS_SUPPORTED="1", SZ_ASYNC_POLL_INTERVAL="0.2")
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    page = c.post("/accept", data={"csrf": csrf_from(html)}).get_data(as_text=True)
    assert "You are connected" in page
    assert [x["RequestType"] for x in nbi.requests] == ["LoginAsync", "Status", "Status"]


def test_authorize_optin_and_304(make_app, nbi):
    app = make_app(SZ_AUTH_METHOD="authorize")
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    assert "You are connected" in c.post("/accept", data={"csrf": csrf_from(html)}).get_data(as_text=True)
    nbi.authorize_supported = False
    nbi.clients.clear()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    r = c.post("/accept", data={"csrf": csrf_from(html)})
    assert r.status_code == 502
    assert any(e["event"] == "auth_result" and e["ResponseCode"] == 304 for e in events(app))


def test_debug_events_stream_own_visit(make_app, nbi):
    app = make_app(PORTAL_MODE="debug")
    c = app.test_client()
    c.get("/", query_string=redirect_qs())
    r = c.get("/events?ref=self", buffered=False)
    assert r.status_code == 200 and r.mimetype == "text/event-stream"
    it = r.response
    first = next(it).decode()
    assert first.startswith("retry:")
    chunk = next(it).decode()
    assert "redirect_received" in chunk and ENC_MAC in chunk     # debug: full values
    r.close()


def test_r1_backend_end_to_end(make_app, nbi, pki):
    """R1 uses the same contract; point it at the fake NBI (vendor 'Ruckus', user 'api')."""
    nbi.username = "api"
    nbi.password = "ikey"
    app = make_app(PORTAL_BACKEND="r1", R1_NBI_HOSTS="127.0.0.1", R1_NBI_PORT=nbi.port,
                   R1_INTEGRATION_KEY="ikey", R1_CA_BUNDLE=pki["ca"])
    c = app.test_client()
    html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
    assert "You are connected" in c.post("/accept", data={"csrf": csrf_from(html)}).get_data(as_text=True)
    assert nbi.requests[-1]["RequestType"] == "Authorize"
    assert nbi.requests[-1]["RequestPassword"] == "ikey"



def _factory_like_cert(tmp_path):
    """Mimic the SZ 9443 factory cert: leaf only, CN=scg.ruckuswireless.com, no SAN, no
    basicConstraints, issued by a CA the portal does not have."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Certificate Authority")])
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "scg.ruckuswireless.com")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA384()))
    cert = tmp_path / "factory-leaf.pem"
    keyf = tmp_path / "factory-key.pem"
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    keyf.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
    import hashlib
    return str(cert), str(keyf), hashlib.sha256(leaf.public_bytes(serialization.Encoding.DER)).hexdigest()


def test_factory_leaf_as_trust_anchor_with_pin(make_app, tmp_path):
    """Lab setup: SZ_CA_BUNDLE = the 9443 leaf itself, name scg.ruckuswireless.com, pinned."""
    import fake_nbi
    import conftest
    cert, key, fp = _factory_like_cert(tmp_path)
    state = fake_nbi.FakeNbiState(username="nbi", password="nbi-secret")
    httpd, _t = fake_nbi.start(state, "127.0.0.1", 0, cert, key)
    state.port = httpd.server_address[1]
    try:
        from server import create_app
        from wispr.config import load_config
        for name, pin, ok in (("scg.ruckuswireless.com", fp, True),
                              ("scg.ruckuswireless.com", "f" * 64, False),
                              ("wrong.example", fp, False)):
            env = {**conftest.base_env(state, {"ca": cert}), "SZ_NBI_PORT": str(httpd.server_address[1]),
                   "SZ_CA_BUNDLE": cert, "SZ_TLS_SERVER_NAME": name, "SZ_CERT_SHA256": fp if pin == fp else pin,
                   "LOG_JSON_PATH": str(tmp_path / "f.jsonl")}
            c = create_app(load_config(env)).test_client()
            html = c.get("/", query_string=redirect_qs()).get_data(as_text=True)
            r = c.post("/accept", data={"csrf": csrf_from(html)})
            assert (r.status_code == 200) is ok, (name, pin[:4])
    finally:
        httpd.shutdown()
