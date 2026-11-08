#!/usr/bin/env python3
"""Local end-to-end check of the hosted portal stack (M-a + M-b):

    fake NBI (TLS, tools/fake_nbi.py)  <--  wispr-connector (python -m connector)
                                              |  WebSocket
                                       wrangler dev (cloud/, ENVIRONMENT=dev)

It checks: the connector connects and applies the pushed config; the hub probes the NBI from
its alarm; guest /healthz goes ok; the token healthz shows details without secrets; guest pages
are served to the connector's egress IP; the guest flow (terms -> accept -> Login through the
connector -> success) with its events in the SSE stream and the query API, key-for-key against
the R3 golden fixture; and healthz goes down when the connector stops.

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
import threading
import time
import urllib.error
import urllib.parse
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


def post_form(port: int, host: str, path: str, fields: dict) -> tuple[int, str]:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST",
                                 headers={"Host": host, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def sse_reader(port: int, token: str, out: list, stop: threading.Event) -> None:
    """Collect SSE frames (id + data) from the events stream until stop is set."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tenants/dha/events/stream",
                                 headers={"Host": "api.test", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        frame: dict = {}
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("id: "):
                frame["id"] = int(line[4:])
            elif line.startswith("data: "):
                frame.update(json.loads(line[6:]))
            elif line == "" and frame:
                out.append(frame)
                frame = {}
            if stop.is_set():
                return


# Golden parity (plan: "Events"): keys the hosted portal adds, and stream fields it drops.
ADDED = {"seq", "client_ip_seen", "via", "connector_ms", "overhead_ms", "client_mac", "uip"}
REMOVED = {"body", "reply"}


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


class Stack:
    """The local stack: fake NBI + wrangler dev, and (after start_connector) the real connector."""

    def __init__(self, extra_env: dict[str, str] | None = None, prefix: str = "cloud-e2e-") -> None:
        self.extra_env = extra_env or {}
        self.prefix = prefix
        self.connector: subprocess.Popen | None = None
        self.wrangler: subprocess.Popen | None = None
        self.httpd = None

    def __enter__(self) -> "Stack":
        self.tmp = tmp = tempfile.mkdtemp(prefix=self.prefix)
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
                     f"SZ_NBI_PASSWORD=nbi-e2e-secret\nSZ_GUEST_PASSWORD=guest-e2e-secret\nCONNECTOR_HOST=localhost\n"
                     f"TENANT_OVERRIDE='{json.dumps(override)}'\n")
            for k, v in self.extra_env.items():
                fh.write(f"{k}={v}\n")

        wport = free_port()
        wrangler = subprocess.Popen(
            ["npx", "wrangler", "dev", "--port", str(wport), "--ip", "127.0.0.1", "--env-file", env_file,
             "--persist-to", os.path.join(tmp, "state"), "--show-interactive-dev-session=false"],
            cwd=os.path.join(ROOT, "cloud"), stdout=open(os.path.join(tmp, "wrangler.log"), "w"),
            stderr=subprocess.STDOUT, start_new_session=True)
        self.wrangler = wrangler
        self.state, self.httpd, self.nbi_port, self.wport = state, httpd, nbi_port, wport
        self.ctoken, self.etoken = ctoken, etoken
        self.guest_host = self.extra_env.get("GUEST_HOST", "guest.test")
        try:
            wait_for("wrangler dev", lambda: http(wport, self.guest_host, "/healthz")[0] in (200, 503), 90)
        except BaseException:
            self.__exit__()
            raise
        return self

    def start_connector(self) -> int:
        """Start the connector; returns its local healthz port."""
        tmp, wport, nbi_port, ctoken = self.tmp, self.wport, self.nbi_port, self.ctoken
        hport = free_port()
        cenv = {**os.environ, "CONNECTOR_URL": f"ws://localhost:{wport}/v1/connect", "CONNECTOR_ALLOW_PLAINTEXT": "1",
                "CONNECTOR_TOKEN": ctoken, "CONNECTOR_ENV": "e2e", "ALLOWED_NBI_HOSTS": "127.0.0.1",
                "ALLOWED_NBI_PORT": str(nbi_port), "GUEST_CIDRS": "10.7.39.0/24",
                "HEALTHZ_LISTEN": f"127.0.0.1:{hport}", "LOG_JSON_PATH": os.path.join(tmp, "connector.jsonl"),
                "PYTHONPATH": ROOT}
        self.connector = subprocess.Popen([sys.executable, "-m", "connector"], cwd=ROOT, env=cenv,
                                          stdout=open(os.path.join(tmp, "connector.log"), "w"), stderr=subprocess.STDOUT)
        self.hport = hport
        wait_for("guest healthz ok", lambda: http(wport, self.guest_host, "/healthz")[0] == 200, 30)
        return hport

    def __exit__(self, *exc) -> None:
        if self.connector:
            self.connector.kill()
        if self.wrangler:
            try:
                os.killpg(self.wrangler.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.wrangler.terminate()
        if self.httpd:
            self.httpd.shutdown()
        print(f"     logs: {self.tmp}")


def main() -> int:
    with Stack() as st:
        wport, etoken, state, tmp = st.wport, st.etoken, st.state, st.tmp
        check(http(wport, "guest.test", "/healthz")[0] == 503, "guest healthz is down before the connector")
        hport = st.start_connector()
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
        check("nbi-e2e-secret" not in text and detail["secrets"] == {"nbi_password": True, "guest_password": True},
              "token healthz: secrets set, no values")
        check(http(wport, "api.test", "/v1/tenants/dha/healthz")[0] == 401, "token healthz needs the token")

        local = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{hport}/healthz", timeout=5).read())
        check(local["wss_connected"] and local["config_applied"], "connector local healthz ok")

        egress = detail["connector"]["egress_ip"]
        print(f"     connector egress seen by the Worker: {egress!r}")
        code, _ = http(wport, "guest.test", "/?client_mac=AA:BB:CC:00:11:22&uip=10.7.39.5")
        check(code == 200, "guest page served to the connector's egress address")

        # ---- M-b: the guest flow, end to end --------------------------------------------------
        golden = json.load(open(os.path.join(ROOT, "cloud", "test", "fixtures", "r3-portal-events.json")))["events"]
        redirect = {k: v for k, v in golden[0]["params"].items() if k != "startUrl"}
        redirect.update(StartURL=golden[0]["params"]["startUrl"], nbiIP="127.0.0.1")
        frames: list = []
        stop = threading.Event()
        threading.Thread(target=sse_reader, args=(wport, etoken, frames, stop), daemon=True).start()
        time.sleep(1.0)
        code, html = http(wport, "guest.test", "/?" + urllib.parse.urlencode(redirect))
        check(code == 200 and html.count('id="accept-button"') == 1, "terms page with one #accept-button")
        ref = html.split('name="ref" value="')[1].split('"')[0]
        csrf = html.split('name="csrf" value="')[1].split('"')[0]
        t0 = time.perf_counter()
        code, html = post_form(wport, "guest.test", "/accept", {"ref": ref, "csrf": csrf})
        accept_ms = (time.perf_counter() - t0) * 1000
        check(code == 200 and 'id="ok-title"' in html, f"accept -> success page ({accept_ms:.0f} ms incl. Login)")
        logins = [r for r in state.requests if r.get("RequestType") == "Login"]
        check(len(logins) == 1 and logins[0].get("UE-MAC") == redirect["client_mac"]
              and logins[0].get("UE-IP") == redirect["uip"]
              and logins[0].get("UE-Password") == "guest-e2e-secret", "exactly one Login, with the tenant's guest password")
        check(post_form(wport, "guest.test", "/accept", {"ref": ref, "csrf": csrf})[0] == 200
              and len([r for r in state.requests if r.get("RequestType") == "Login"]) == 1,
              "a resubmit shows success again without a second Login")

        code, text = http(wport, "api.test", f"/v1/tenants/dha/events?ref={ref}&limit=1000", token=etoken)
        got = [e for e in json.loads(text)["events"] if e["event"] != "success_shown" or not e.get("repeat")]
        check([e["event"] for e in got] == [e["event"] for e in golden], "query: the lab's event sequence")
        for want, have in zip(golden, got):
            keys_want = sorted(k for k in want if k not in REMOVED)
            keys_have = sorted(k for k in have if k not in ADDED or k in want)
            check(keys_have == keys_want, f"golden keys: {have['event']}")
        auth = next(e for e in got if e["event"] == "auth_result")
        print(f"     NBI total_ms={auth['total_ms']} connector_ms={auth['connector_ms']} overhead_ms={auth['overhead_ms']}")
        check(all(e.get("ref") == ref for e in got) and "nbi-e2e-secret" not in text, "events carry the ref, no password")
        wait_for("SSE frames", lambda: sum(1 for f in frames if f.get("ref") == ref) >= len(golden), 10)
        stop.set()
        streamed = [f for f in frames if f.get("ref") == ref]
        check([f["event"] for f in streamed][:len(golden)] == [e["event"] for e in golden]
              and all(f["id"] == e["seq"] for f, e in zip(streamed, got)), "SSE: same events, id = seq")

        log_text = open(os.path.join(tmp, "connector.jsonl")).read()
        check("nbi-e2e-secret" not in log_text and "nbi_probe" in log_text, "connector log: probes, no password")

        st.connector.send_signal(signal.SIGTERM)
        st.connector.wait(10)
        st.connector = None
        wait_for("guest healthz down after the connector stops",
                 lambda: http(wport, "guest.test", "/healthz")[0] == 503, 20)
        check(True, "guest healthz down after the connector stops")
        print("PASS")
        return 0


if __name__ == "__main__":
    sys.exit(main())
