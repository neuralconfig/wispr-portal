import os
import sys

import pytest
import trustme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ["WISPR_NO_AUTOAPP"] = "1"

import fake_nbi  # noqa: E402

ENC_MAC = fake_nbi.fake_encrypt("AA:BB:CC:DD:EE:01")
ENC_IP = fake_nbi.fake_encrypt("10.7.39.50")


@pytest.fixture(scope="session")
def pki(tmp_path_factory):
    d = tmp_path_factory.mktemp("pki")
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1", "scg.ruckuswireless.com")
    leaf.cert_chain_pems[0].write_to_path(str(d / "cert.pem"))
    leaf.private_key_pem.write_to_path(str(d / "key.pem"))
    ca.cert_pem.write_to_path(str(d / "ca.pem"))
    other = trustme.CA()
    other.cert_pem.write_to_path(str(d / "other-ca.pem"))
    return {"cert": str(d / "cert.pem"), "key": str(d / "key.pem"), "ca": str(d / "ca.pem"),
            "other_ca": str(d / "other-ca.pem"), "leaf": leaf}


@pytest.fixture
def nbi(pki):
    state = fake_nbi.FakeNbiState(username="nbi", password="nbi-secret", status_supported=False)
    httpd, _t = fake_nbi.start(state, "127.0.0.1", 0, pki["cert"], pki["key"])
    state.port = httpd.server_address[1]
    yield state
    httpd.shutdown()


def base_env(nbi_state, pki, **over):
    env = {
        "PORTAL_BACKEND": "smartzone",
        "PORTAL_MODE": "customer",
        "SZ_NBI_HOSTS": "127.0.0.1",
        "SZ_NBI_PORT": str(nbi_state.port),
        "SZ_NBI_USERNAME": "nbi",
        "SZ_NBI_PASSWORD": "nbi-secret",
        "SZ_CA_BUNDLE": pki["ca"],
        "SZ_NBI_TIMEOUT": "5",
        "SECRET_KEY": "x" * 40,
        "LOG_CONSOLE": "0",
    }
    env.update({k: str(v) for k, v in over.items()})
    return env


@pytest.fixture
def make_app(nbi, pki, tmp_path):
    from server import create_app
    from wispr.config import load_config

    def _make(**over):
        log_path = tmp_path / "events.jsonl"
        env = base_env(nbi, pki, LOG_JSON_PATH=str(log_path), **over)
        app = create_app(load_config(env))
        app.config["TESTING"] = True
        app.log_path = log_path
        return app

    return _make


def redirect_qs(**over):
    q = {"client_mac": ENC_MAC, "uip": ENC_IP, "nbiIP": "127.0.0.1", "mac": "04:4f:aa:32:25:f0",
         "ssid": "Guest", "url": "http://connectivitycheck.gstatic.com/generate_204",
         "reason": "Un-Auth-Captive", "proxy": "0", "vlan": "739", "wlan": "3"}
    q.update(over)
    return {k: v for k, v in q.items() if v is not None}
