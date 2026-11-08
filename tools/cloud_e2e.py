#!/usr/bin/env python3
"""Local end-to-end check of the hosted portal stack (M-a):

    fake NBI (TLS, tools/fake_nbi.py)  <--  wispr-connector (python -m connector)
                                              |  WebSocket
                                       wrangler dev (cloud/, ENVIRONMENT=dev)

It checks: the connector connects and applies the pushed config; the hub probes the NBI from
its alarm; guest /healthz goes ok; the token healthz shows details without secrets; guest pages
are served to the connector's egress IP; and healthz goes down when the connector stops.

    .venv/bin/python tools/cloud_e2e.py          (needs cloud/node_modules: cd cloud && npm ci)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]

import fake_nbi  # noqa: E402
import trustme  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(port: int, host: str, path: str, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, ""


def wait_for(what: str, fn, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = fn()
        if got:
            return got
        time.sleep(0.5)
    raise SystemExit(f"FAIL: timed out waiting for {what}")


def check(cond: bool, what: str) -> None:
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        raise SystemExit(1)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="cloud-e2e-")
    ca = trustme.CA()
    leaf = ca.issue_cert("127.0.0.1")
    cert, key = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
    leaf.cert_chain_pems[0].write_to_path(cert)
    leaf.private_key_pem.write_to_path(key)
    ca_pem = ca.cert_pem.bytes().decode()

    state = fake_nbi.FakeNbiState(username="dha-nbi", password="nbi-e2e-secret", status_supported=True)
    httpd, _ = fake_nbi.start(state, "127.0.0.1", 0, cert, key)
    nbi_port = httpd.server_address[1]

    ctoken, etoken = f"wpc_dha_{secrets.token_hex(16)}", f"wpe_dha_{secrets.token_hex(16)}"
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    override = {"nbi": {"hosts": ["127.0.0.1"], "port": nbi_port, "tls_server_name": None,
                        "cert_sha256": None, "ca_pem": ca_pem, "timeout_s": 5},
                "probe_interval_s": 2, "reconnect_grace_s": 2}
    env_file = os.path.join(tmp, "dev.env")
    with open(env_file, "w") as fh:
        fh.write(f"CONNECTOR_TOKEN_SHA256={sha(ctoken)}\nEVENTS_TOKEN_SHA256={sha(etoken)}\n"
                 f"SZ_NBI_PASSWORD=nbi-e2e-secret\nCONNECTOR_HOST=localhost\n"
                 f"TENANT_OVERRIDE='{json.dumps(override)}'\n")

    wport = free_port()
    wrangler = subprocess.Popen(
        ["npx", "wrangler", "dev", "--port", str(wport), "--ip", "127.0.0.1", "--env-file", env_file,
         "--persist-to", os.path.join(tmp, "state"), "--show-interactive-dev-session=false"],
        cwd=os.path.join(ROOT, "cloud"), stdout=open(os.path.join(tmp, "wrangler.log"), "w"),
        stderr=subprocess.STDOUT, start_new_session=True)
    connector = None
    try:
        wait_for("wrangler dev", lambda: http(wport, "guest.test", "/healthz")[0] in (200, 503), 90)
        check(http(wport, "guest.test", "/healthz")[0] == 503, "guest healthz is down before the connector")

        hport = free_port()
        cenv = {**os.environ, "CONNECTOR_URL": f"ws://localhost:{wport}/v1/connect", "CONNECTOR_ALLOW_PLAINTEXT": "1",
                "CONNECTOR_TOKEN": ctoken, "CONNECTOR_ENV": "e2e", "ALLOWED_NBI_HOSTS": "127.0.0.1",
                "ALLOWED_NBI_PORT": str(nbi_port), "GUEST_CIDRS": "10.7.39.0/24",
                "HEALTHZ_LISTEN": f"127.0.0.1:{hport}", "LOG_JSON_PATH": os.path.join(tmp, "connector.jsonl"),
                "PYTHONPATH": ROOT}
        connector = subprocess.Popen([sys.executable, "-m", "connector"], cwd=ROOT, env=cenv,
                                     stdout=open(os.path.join(tmp, "connector.log"), "w"), stderr=subprocess.STDOUT)

        body = wait_for("guest healthz ok", lambda: (lambda r: r[0] == 200 and json.loads(r[1]))(
            http(wport, "guest.test", "/healthz")), 30)
        check(body["connector"]["connected"] and body["nbi"][0]["reachable"], "connector connected, node1 reachable")
        check("127.0.0.1" not in json.dumps(body), "public healthz shows no addresses")
        check(any(r.get("RequestType") == "Status" and r.get("UE-MAC") == "02:00:00:00:00:00" for r in state.requests),
              "the probe reached the NBI as Status for the dummy UE")

        code, text = http(wport, "api.test", "/v1/tenants/dha/healthz", token=etoken)
        detail = json.loads(text)
        check(code == 200 and detail["connector"]["applied"]["ca_source"] == "cloud", "token healthz: config applied from the cloud")
        check(detail["nbi"][0]["tls"]["cert_sha256"] != "", "token healthz: TLS details of the probe")
        check("nbi-e2e-secret" not in text, "token healthz carries no NBI password")
        check(http(wport, "api.test", "/v1/tenants/dha/healthz")[0] == 401, "token healthz needs the token")

        local = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{hport}/healthz", timeout=5).read())
        check(local["wss_connected"] and local["config_applied"], "connector local healthz ok")

        egress = detail["connector"]["egress_ip"]
        print(f"     connector egress seen by the Worker: {egress!r}")
        code, _ = http(wport, "guest.test", "/?client_mac=AA:BB:CC:00:11:22&uip=10.7.39.5")
        check(code == 200, "guest page served to the connector's egress address")

        log_text = open(os.path.join(tmp, "connector.jsonl")).read()
        check("nbi-e2e-secret" not in log_text and "nbi_probe" in log_text, "connector log: probes, no password")

        connector.send_signal(signal.SIGTERM)
        connector.wait(10)
        connector = None
        wait_for("guest healthz down after the connector stops",
                 lambda: http(wport, "guest.test", "/healthz")[0] == 503, 20)
        check(True, "guest healthz down after the connector stops")
        print("PASS")
        return 0
    finally:
        if connector:
            connector.kill()
        try:
            os.killpg(wrangler.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            wrangler.terminate()
        httpd.shutdown()
        print(f"     logs: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
