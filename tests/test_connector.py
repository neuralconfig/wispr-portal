"""wispr-connector: policy ceiling, NBI operations against the fake NBI, and a full WSS session
against a fake hub (the Worker side is tested in cloud/test)."""

import asyncio
import json
import ssl

import pytest

import fake_nbi
from connector import ops
from connector.main import PING, PONG, Connector
from connector.policy import PolicyError, RateLimiter, build_nbi_config, check_accept, describe
from connector.settings import load_settings
from wispr.config import ConfigError
from wispr.nbi import NbiClient, check_peer_name


def settings_env(port=9443, **over):
    env = {
        "CONNECTOR_URL": "wss://guest-connector.example/v1/connect",
        "CONNECTOR_TOKEN": "wpc_dha_test",
        "ALLOWED_NBI_HOSTS": "127.0.0.1,192.168.37.8",
        "ALLOWED_NBI_PORT": str(port),
        "GUEST_CIDRS": "10.7.39.0/24",
        "HEALTHZ_LISTEN": "127.0.0.1:0",
    }
    env.update({k: str(v) for k, v in over.items()})
    return env


def cloud_config(pki, port=9443, **over):
    with open(pki["ca"], encoding="utf-8") as fh:
        ca = fh.read()
    cfg = {"backend": "smartzone", "hosts": ["127.0.0.1"], "port": port, "request_username": "nbi",
           "request_password": "nbi-secret", "auth_method": "login", "guest_username": "dha-guest",
           "status_supported": True, "timeout_s": 5, "ca_pem": ca}
    cfg.update(over)
    return cfg


@pytest.fixture
def nbi_status(pki):
    state = fake_nbi.FakeNbiState(username="nbi", password="nbi-secret", status_supported=True)
    httpd, _t = fake_nbi.start(state, "127.0.0.1", 0, pki["cert"], pki["key"])
    state.port = httpd.server_address[1]
    yield state
    httpd.shutdown()


# ---- settings and policy ------------------------------------------------------------------

def test_settings_require_wss_token_and_ceiling():
    load_settings(settings_env())
    for bad in ({"CONNECTOR_URL": "ws://x/v1/connect"}, {"CONNECTOR_TOKEN": ""}, {"ALLOWED_NBI_HOSTS": ""},
                {"GUEST_CIDRS": ""}, {"GUEST_CIDRS": "nope"}, {"ALLOWED_METHODS": "logout"},
                {"CONNECTOR_IP_FAMILY": "5"}):
        with pytest.raises(ConfigError):
            load_settings(settings_env(**bad))


def test_policy_refuses_anything_outside_the_ceiling(pki):
    s = load_settings(settings_env())
    nbi = build_nbi_config(cloud_config(pki), s)
    assert nbi.hosts == ("127.0.0.1",) and nbi.ca_pem and nbi.ca_bundle is None
    for over in ({"hosts": ["192.168.37.9"]}, {"hosts": []}, {"port": 443}, {"auth_method": "logout"},
                 {"auth_method": "login_async", "status_supported": False}, {"request_password": ""},
                 {"ca_pem": "not a pem"}, {"ca_pem": None}, {"tls_max_version": "1.0"},
                 {"cert_sha256": "abc"}, {"backend": "r1"}, {"timeout_s": 0}):
        with pytest.raises(PolicyError):
            build_nbi_config(cloud_config(pki, **over), s)
    # authorize is allowed by default, login_async only when listed
    build_nbi_config(cloud_config(pki, auth_method="authorize"), s)
    s2 = load_settings(settings_env(ALLOWED_METHODS="login"))
    with pytest.raises(PolicyError):
        build_nbi_config(cloud_config(pki, auth_method="authorize"), s2)


def test_local_ca_bundle_is_the_fallback_anchor(pki):
    s = load_settings(settings_env(SZ_CA_BUNDLE=pki["ca"]))
    nbi = build_nbi_config(cloud_config(pki, ca_pem=None), s)
    assert nbi.ca_bundle == pki["ca"] and nbi.ca_pem is None
    assert describe(nbi)["ca_source"] == "local"


def test_accept_args_must_name_a_guest_ip():
    s = load_settings(settings_env())
    assert check_accept({"client_mac": "AA:BB:CC:DD:EE:01", "uip": "10.7.39.50", "proxy": "0"}, s)["uip"] == "10.7.39.50"
    for bad in ({"client_mac": "AA", "uip": "10.7.40.1"}, {"client_mac": "AA", "uip": "ENC0102"},
                {"uip": "10.7.39.5"}, {"client_mac": "AA", "uip": 5}, "x"):
        with pytest.raises(PolicyError):
            check_accept(bad, s)


def test_rate_limiter():
    r = RateLimiter(2)
    assert r.take() and r.take() and not r.take()


# ---- the name check that replaced OpenSSL's CN fallback -------------------------------------

def test_check_peer_name():
    cn_only = {"subject": ((("commonName", "scg.ruckuswireless.com"),),)}
    check_peer_name(cn_only, "scg.ruckuswireless.com")
    check_peer_name(cn_only, "SCG.ruckuswireless.com.")
    for name in ("other.example", "192.168.37.6"):
        with pytest.raises(ssl.SSLCertVerificationError):
            check_peer_name(cn_only, name)
    with_san = {"subject": ((("commonName", "cn.example"),),),
                "subjectAltName": (("DNS", "*.lab.example"), ("IP Address", "10.0.0.1"))}
    check_peer_name(with_san, "nbi.lab.example")
    check_peer_name(with_san, "10.0.0.1")
    for name in ("cn.example", "a.b.lab.example", "lab.example", "10.0.0.2"):   # SAN present: CN ignored
        with pytest.raises(ssl.SSLCertVerificationError):
            check_peer_name(with_san, name)


# ---- operations against the fake NBI ---------------------------------------------------------

def test_probe_and_accept(nbi_status, pki, tmp_path):
    s = load_settings(settings_env(port=nbi_status.port))
    client = NbiClient(build_nbi_config(cloud_config(pki, port=nbi_status.port), s))
    log = ops.JsonlLog(str(tmp_path / "c.jsonl"))

    p = ops.probe(client, "127.0.0.1", log)
    assert p["reachable"] and p["code"] == 100 and p["tls"]["cert_sha256"]
    assert nbi_status.requests[-1]["RequestType"] == "Status"
    assert nbi_status.requests[-1]["UE-MAC"] == ops.PROBE_MAC
    assert ops.probe(client, "192.168.37.8", log)["error_kind"] == "not_allowed"   # in the ceiling, not configured
    assert not ops.probe(client, "10.9.9.9", log)["reachable"]

    r = ops.accept(client, "ABCD-EFGH", {"client_mac": "AA:BB:CC:DD:EE:01", "uip": "10.7.39.50", "proxy": "0"}, log)
    assert r["ok"] and r["outcome"] == "authorized" and r["code"] == 201
    names = [e["event"] for e in r["events"]]
    assert names == ["nbi_request", "nbi_response", "auth_result"]
    req = r["events"][0]
    assert req["body"]["RequestPassword"] != "nbi-secret" and req["body"]["UE-Username"] == "dha-guest"
    text = (tmp_path / "c.jsonl").read_text()
    assert "nbi-secret" not in text and "nbi_probe" in text and "auth_result" in text

    # wrong NBI password: the node answers 306, which counts as down
    s_bad = build_nbi_config(cloud_config(pki, port=nbi_status.port, request_password="wrong"), s)
    assert not ops.probe(NbiClient(s_bad), "127.0.0.1", log)["reachable"]


# ---- a full session against a fake hub ---------------------------------------------------------

def test_session_with_fake_hub(nbi_status, pki, tmp_path):
    from websockets.asyncio.server import serve

    seen = {}

    async def hub(ws):
        seen["auth"] = ws.request.headers.get("Authorization")
        hello = json.loads(await ws.recv())
        seen["hello"] = hello
        await ws.send(json.dumps({"type": "config", "config": cloud_config(pki, port=nbi_status.port)}))
        seen["applied"] = await recv_json(ws)
        await ws.send(json.dumps({"type": "rpc", "id": "1", "op": "probe", "args": {"host": "127.0.0.1"}}))
        seen["probe"] = await recv_json(ws)
        await ws.send(json.dumps({"type": "rpc", "id": "2", "op": "accept", "args": {
            "ref": "WXYZ-2345", "params": {"client_mac": "AA:BB:CC:DD:EE:02", "uip": "10.7.39.51"}}}))
        seen["accept"] = await recv_json(ws)
        await ws.send(json.dumps({"type": "rpc", "id": "3", "op": "accept", "args": {
            "ref": "WXYZ-2345", "params": {"client_mac": "AA:BB:CC:DD:EE:02", "uip": "8.8.8.8"}}}))
        seen["refused"] = await recv_json(ws)
        await ws.send(json.dumps({"type": "rpc", "id": "4", "op": "logout", "args": {}}))
        seen["logout"] = await recv_json(ws)
        seen["health"] = conn.health()
        await ws.close()

    async def recv_json(ws):
        while True:
            raw = await ws.recv()
            if raw == PING:
                await ws.send(PONG)
                continue
            return json.loads(raw)

    async def scenario():
        nonlocal conn
        async with serve(hub, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            s = load_settings(settings_env(port=nbi_status.port, CONNECTOR_URL=f"ws://127.0.0.1:{port}/v1/connect",
                                           CONNECTOR_ALLOW_PLAINTEXT="1", LOG_JSON_PATH=str(tmp_path / "s.jsonl")))
            conn = Connector(s)
            await asyncio.wait_for(conn.session(), timeout=20)

    conn = None
    asyncio.run(scenario())

    assert seen["auth"] == "Bearer wpc_dha_test"
    assert seen["hello"]["type"] == "hello" and seen["hello"]["ceiling"]["guest_cidrs"] == ["10.7.39.0/24"]
    assert seen["applied"]["type"] == "config_applied" and seen["applied"]["ca_source"] == "cloud"
    assert seen["probe"]["ok"] and seen["probe"]["result"]["reachable"]
    assert seen["accept"]["ok"] and seen["accept"]["result"]["outcome"] == "authorized"
    assert not seen["refused"]["ok"] and seen["refused"]["error"] == "policy"
    assert not seen["logout"]["ok"] and "not allowed" in seen["logout"]["detail"]
    status, body = seen["health"]
    assert status == 200 and body["wss_connected"] and body["last_probe"]["127.0.0.1"]["reachable"]
    assert "nbi-secret" not in (tmp_path / "s.jsonl").read_text()


def test_config_rejected_is_reported(pki, tmp_path):
    from websockets.asyncio.server import serve

    seen = {}

    async def hub(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "config", "config": cloud_config(pki, hosts=["10.1.1.1"])}))
        seen["reply"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "rpc", "id": "1", "op": "probe", "args": {"host": "127.0.0.1"}}))
        seen["rpc"] = json.loads(await ws.recv())
        await ws.close()

    async def scenario():
        async with serve(hub, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            s = load_settings(settings_env(CONNECTOR_URL=f"ws://127.0.0.1:{port}/v1/connect",
                                           CONNECTOR_ALLOW_PLAINTEXT="1", LOG_JSON_PATH=str(tmp_path / "r.jsonl")))
            await asyncio.wait_for(Connector(s).session(), timeout=10)

    asyncio.run(scenario())
    assert seen["reply"]["type"] == "config_rejected" and "ALLOWED_NBI_HOSTS" in seen["reply"]["error"]
    assert not seen["rpc"]["ok"] and "no configuration" in seen["rpc"]["detail"]
