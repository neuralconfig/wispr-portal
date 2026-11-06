#!/usr/bin/env python3
"""Fake RUCKUS WISPr northbound interface (SmartZone / RUCKUS One style) for tests and demos.

It implements the JSON contract described in SZ-wispr-api.md: POST /portalintf with
Vendor/APIVersion/RequestUserName/RequestPassword/RequestCategory/RequestType, the
UserOnlineControl commands and GetConfig Encrypt/Decrypt, and the documented reply codes.
It is NOT the real controller: behaviour the docs leave open is configurable.

    python tools/fake_nbi.py --port 9443 --cert cert.pem --key key.pem --password secret

Without --cert/--key it needs the 'trustme' package and writes a throwaway CA to
--ca-out so the portal can verify it (SZ_CA_BUNDLE=<that file>).
"""

from __future__ import annotations

import argparse
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENC_PREFIX = "ENC"


def fake_encrypt(clear: str) -> str:
    return ENC_PREFIX + clear.encode("utf-8").hex()


def fake_decrypt(enc: str) -> str | None:
    if not enc.startswith(ENC_PREFIX):
        return enc
    try:
        return bytes.fromhex(enc[3:]).decode("utf-8")
    except ValueError:
        return None


class FakeNbiState:
    def __init__(self, username="nbi", password="secret", vendor="ruckus",
                 status_supported=True, authorize_supported=True, login_delay_s=0.0,
                 async_steps=1, unknown_macs=(), reject_users=()):
        self.username = username
        self.password = password
        self.vendor = vendor
        self.status_supported = status_supported
        self.authorize_supported = authorize_supported
        self.login_delay_s = login_delay_s
        self.async_steps = async_steps
        self.unknown_macs = set(unknown_macs)
        self.reject_users = set(reject_users)
        self.clients: dict[str, str] = {}          # mac -> unauthorized|authorized|pending:N|failed
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    # Every reply carries Vendor/APIVersion/ResponseCode/ReplyMessage (SZ guide p.45-47).
    def reply(self, code: int, msg: str, **extra) -> dict:
        return {"Vendor": "Ruckus", "APIVersion": "1.0", "ResponseCode": code, "ReplyMessage": msg, **extra}

    def handle(self, body: dict) -> dict:
        with self.lock:
            self.requests.append(body)
        if not isinstance(body, dict) or str(body.get("Vendor", "")).lower() != self.vendor.lower():
            return self.reply(302, "Bad request")
        if body.get("APIVersion") != "1.0":
            return self.reply(303, "Version not supported")
        if body.get("RequestPassword") != self.password or \
                (self.username and body.get("RequestUserName") != self.username):
            return self.reply(306, "Wrong request password")
        cat, typ = body.get("RequestCategory"), body.get("RequestType")
        if cat == "GetConfig":
            if typ == "Decrypt":
                clear = fake_decrypt(str(body.get("Data", "")))
                return self.reply(200, "OK", Data=clear) if clear else self.reply(302, "Bad request")
            if typ == "Encrypt":
                return self.reply(200, "OK", Data=fake_encrypt(str(body.get("Data", ""))))
            return self.reply(304, "Command not supported")
        if cat != "UserOnlineControl":
            return self.reply(305, "Category not supported")
        if typ not in ("Login", "LoginAsync", "Status", "Logout", "Disconnect", "Authorize", "EnrichmentInfo"):
            return self.reply(304, "Command not supported")
        if typ == "Status" and not self.status_supported:
            return self.reply(304, "Command not supported")
        if typ == "Authorize" and not self.authorize_supported:
            return self.reply(304, "Command not supported")

        mac_enc = body.get("UE-MAC")
        if not mac_enc:
            return self.reply(302, "Bad request")
        mac = fake_decrypt(str(mac_enc))
        if mac is None:
            return self.reply(302, "Bad request")
        if mac.lower() in self.unknown_macs:
            return self.reply(300, "Not found")
        ue = {"UE-MAC": mac_enc, "UE-IP": body.get("UE-IP", ""), "AP-MAC": "04:4f:aa:32:25:f0",
              "SSID": "Guest", "SmartClientMode": "none", "SmartClientInfo": "", "GuestUser": "0"}

        with self.lock:
            state = self.clients.get(mac, "unauthorized")
            if typ in ("Login", "Authorize"):
                if state == "authorized":
                    return self.reply(101, "Client authorized", **ue)
                if self.login_delay_s:
                    time.sleep(self.login_delay_s)
                if typ == "Login" and body.get("UE-Username") in self.reject_users:
                    self.clients[mac] = "unauthorized"
                    return self.reply(301, "Login failed", **ue)
                self.clients[mac] = "authorized"
                return self.reply(201, "Login succeeded", **ue,
                                  **({"UE-Username": body.get("UE-Username")} if typ == "Login" else {}))
            if typ == "LoginAsync":
                if state == "authorized":
                    return self.reply(101, "Client authorized", **ue)
                self.clients[mac] = f"pending:{self.async_steps}"
                return self.reply(202, "Authentication pending", **ue)
            if typ == "Status":
                if state.startswith("pending:"):
                    left = int(state.split(":")[1]) - 1
                    if left > 0:
                        self.clients[mac] = f"pending:{left}"
                        return self.reply(202, "Authentication pending", **ue)
                    self.clients[mac] = "authorized"
                    return self.reply(201, "Login succeeded", **ue)
                if state == "authorized":
                    return self.reply(101, "Client authorized", **ue)
                return self.reply(100, "Client unauthorized", **ue)
            if typ in ("Logout", "Disconnect"):
                if state != "authorized":
                    return self.reply(100, "Client unauthorized", **ue)
                self.clients[mac] = "unauthorized"
                return self.reply(200, "OK", **ue)
            return self.reply(102, "Enrichment Information", **ue)


def make_handler(state: FakeNbiState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FakeNBI"
        sys_version = ""

        def log_message(self, fmt, *args):   # quiet
            pass

        def do_GET(self):
            self.send_response(405)
            self.end_headers()

        def do_POST(self):
            if self.path != "/portalintf":
                # SZ replies with an empty response for a wrong URI (Confluence NBI commands page).
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(min(length, 65536))
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = None
            reply = state.handle(body) if isinstance(body, dict) else state.reply(302, "Bad request")
            data = json.dumps(reply).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start(state: FakeNbiState, host: str, port: int, certfile: str, keyfile: str):
    """Start in a background thread. Returns (server, thread). port=0 picks a free port."""
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE+AESGCM")
    ctx.load_cert_chain(certfile, keyfile)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9443)
    ap.add_argument("--cert")
    ap.add_argument("--key")
    ap.add_argument("--ca-out", default="fake-nbi-ca.pem")
    ap.add_argument("--username", default="nbi")
    ap.add_argument("--password", default="secret")
    ap.add_argument("--no-status", action="store_true", help="answer Status with 304 (vSZ-H per the 7.0 guide)")
    ap.add_argument("--no-authorize", action="store_true", help="answer Authorize with 304")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to wait before a Login reply")
    args = ap.parse_args()

    certfile, keyfile = args.cert, args.key
    if not certfile:
        import tempfile

        import trustme
        ca = trustme.CA()
        leaf = ca.issue_cert(args.host, "scg.ruckuswireless.com")
        tmp = tempfile.mkdtemp(prefix="fake-nbi-")
        certfile, keyfile = f"{tmp}/cert.pem", f"{tmp}/key.pem"
        leaf.cert_chain_pems[0].write_to_path(certfile)
        leaf.private_key_pem.write_to_path(keyfile)
        ca.cert_pem.write_to_path(args.ca_out)
        print(f"CA written to {args.ca_out} (set SZ_CA_BUNDLE to it)")

    state = FakeNbiState(username=args.username, password=args.password,
                         status_supported=not args.no_status, authorize_supported=not args.no_authorize,
                         login_delay_s=args.delay)
    httpd, t = start(state, args.host, args.port, certfile, keyfile)
    print(f"fake NBI on https://{args.host}:{args.port}/portalintf  (user {args.username!r})")
    try:
        t.join()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
