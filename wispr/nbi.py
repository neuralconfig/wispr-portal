"""Northbound-interface client: request building, TLS, allowlist, response codes.

SmartZone: POST https://<controller>:9443/portalintf, JSON, POST only
(SZ 7.0.0 Hotspot WISPr Interface Reference Guide, "Request Format" p.35 and
"Controller Web Interface Configuration" p.36). RUCKUS One: POST
https://<tenant>.wispr.ruckus.cloud:443/portalintf. See SZ-wispr-api.md.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import time
from dataclasses import dataclass, field

from .config import NbiConfig
from .params import normalize_host

# ResponseCode table: SZ 7.0 guide Table 15 (p.44); R1 reference "JSON Responses Definitions".
REPLY_CODES = {
    100: "Client unauthorized",
    101: "Client authorized",
    102: "Enrichment Info",
    200: "OK",
    201: "Login succeeded",
    202: "Authentication pending",
    300: "Not found",
    301: "Login failed",
    302: "Bad request",
    303: "Version not supported",
    304: "Command not supported",
    305: "Category not supported",
    306: "Wrong request password",
    400: "Internal server error",
    401: "Authentication server error",
}

# Outcome classes used by the pages.
AUTHORIZED = {101, 201}
SUCCESS_TYPES = {200}
PENDING = {202}
NOT_FOUND = {300}
LOGIN_FAILED = {100, 301}
PORTAL_CONFIG = {302, 303, 304, 305, 306}
CONTROLLER = {400, 401}

# NBI wire names. The public SZ guide spells them Login/LoginAsync/Status/Logout/Disconnect;
# Authorize is not in the public SZ guide (see SZ-wispr-api.md).
REQUEST_TYPES = {
    "login": "Login",
    "login_async": "LoginAsync",
    "authorize": "Authorize",
    "status": "Status",
    "logout": "Logout",
    "disconnect": "Disconnect",
    "decrypt": "Decrypt",
}

FIPS_CIPHERS_TLS12 = ("ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
                      "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256")


class NbiError(Exception):
    """Transport-level failure (no usable NBI reply)."""

    def __init__(self, kind: str, detail: str, host: str | None = None):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind            # not_allowed | connect | tls | timeout | http | bad_reply
        self.detail = detail
        self.host = host


class HostNotAllowed(NbiError):
    def __init__(self, host: str):
        super().__init__("not_allowed", f"NBI host {host!r} is not in the allowlist", host)


@dataclass
class NbiExchange:
    """One request/response, kept for logs and the debug page."""

    request_type: str
    host: str
    url: str
    body: dict
    started: float
    duration_ms: float = 0.0
    http_status: int | None = None
    reply: dict | None = None
    error: NbiError | None = None
    tls: dict = field(default_factory=dict)

    @property
    def code(self) -> int | None:
        if not self.reply:
            return None
        try:
            return int(self.reply.get("ResponseCode"))
        except (TypeError, ValueError):
            return None

    @property
    def message(self) -> str:
        return str((self.reply or {}).get("ReplyMessage", ""))


def make_ssl_context(cfg: NbiConfig) -> ssl.SSLContext:
    """Verifying client context: TLS 1.2+, ECDHE + AES-GCM only (FIPS CG 7.1.1.3
    https-client-security-level 2/3 suites). The TLS 1.3 suites OpenSSL offers by default
    include ChaCha20, but a FIPS SmartZone only selects AES-GCM. Pin TLS 1.2 with
    *_TLS_MAX_VERSION=1.2 if a strict AES-GCM-only offer is required."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cfg.ca_bundle)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if cfg.tls_max_version == "1.2":
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(FIPS_CIPHERS_TLS12)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class _VerifiedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that verifies the certificate against ``server_name`` (which may
    differ from the IP we connect to, e.g. the SZ factory cert CN scg.ruckuswireless.com)
    and optionally pins the leaf certificate's SHA-256 fingerprint."""

    def __init__(self, host, port, *, context, server_name, pin, connect_timeout, timeout):
        super().__init__(host, port, timeout=timeout, context=context)
        self._server_name = server_name
        self._pin = pin
        self._connect_timeout = connect_timeout
        self.tls_info: dict = {}

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self._connect_timeout)
        sock.settimeout(self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self._server_name)
        except Exception:
            sock.close()
            raise
        der = self.sock.getpeercert(binary_form=True) or b""
        fp = hashlib.sha256(der).hexdigest()
        self.tls_info = {
            "version": self.sock.version(),
            "cipher": (self.sock.cipher() or ("",))[0],
            "server_name": self._server_name,
            "cert_sha256": fp,
        }
        if self._pin and fp != self._pin:
            self.sock.close()
            raise ssl.SSLCertVerificationError(f"certificate fingerprint {fp} does not match the pinned value")


class NbiClient:
    def __init__(self, cfg: NbiConfig):
        self.cfg = cfg
        self._ctx = make_ssl_context(cfg)

    # ---- host selection -------------------------------------------------------------
    def allowed(self, host: str | None) -> bool:
        return bool(host) and host.lower() in self.cfg.hosts

    def hosts_for(self, nbi_param: str | None) -> list[str]:
        """Order of NBI hosts to try. The redirect's nbiIP goes first, but only when it is in
        the allowlist; an nbiIP outside the allowlist is refused (no SSRF). Without nbiIP the
        allowlist order is used. Other allowlisted hosts are fallbacks for connect errors."""
        hosts = list(self.cfg.hosts)
        if nbi_param:
            host = normalize_host(nbi_param)
            if not host or not self.allowed(host):
                raise HostNotAllowed(host or nbi_param[:80])
            hosts.remove(host)
            hosts.insert(0, host)
        return hosts

    # ---- request building -----------------------------------------------------------
    def base_body(self, request_type: str, category: str = "UserOnlineControl") -> dict:
        body = {
            "Vendor": self.cfg.vendor,
            "RequestUserName": self.cfg.request_username,
            "RequestPassword": self.cfg.request_password,
            "APIVersion": self.cfg.api_version,
            "RequestCategory": category,
            "RequestType": REQUEST_TYPES[request_type],
        }
        if not self.cfg.request_username:
            del body["RequestUserName"]
        return body

    def build(self, request_type: str, params, data: str | None = None) -> dict:
        """Build the JSON body. UE-MAC / UE-IP are passed back exactly as received in the
        redirect (encrypted ENC... or clear, in the portal profile's MAC format): the NBI
        decrypts them itself (SZ guide p.37 note; R1 reference note)."""
        if request_type == "decrypt":
            body = self.base_body("decrypt", category="GetConfig")
            body["Data"] = data or ""
            return body
        body = self.base_body(request_type)
        mac = params.get("client_mac")
        uip = params.get("uip")
        if uip:
            body["UE-IP"] = uip
        if mac:
            body["UE-MAC"] = mac
        if request_type in ("login", "login_async"):
            body["UE-Proxy"] = params.get("proxy") or "0"
            body["UE-Username"] = self.cfg.guest_username
            body["UE-Password"] = self.cfg.guest_password
        return body

    # ---- transport ------------------------------------------------------------------
    def send(self, request_type: str, body: dict, hosts: list[str]) -> NbiExchange:
        """POST to the first host that accepts a TCP/TLS connection. Fails over only on
        connect errors (the request never reached a controller); a timeout after sending is
        not retried, because the controller may have acted on it."""
        last = None
        for host in hosts:
            if not self.allowed(host):          # defence in depth
                raise HostNotAllowed(host)
            ex = self._post_once(request_type, host, body)
            if ex.error is None or ex.error.kind not in ("connect",):
                return ex
            last = ex
        return last

    def _post_once(self, request_type: str, host: str, body: dict) -> NbiExchange:
        port = self.cfg.port
        host_part = f"[{host}]" if ":" in host else host
        url = f"https://{host_part}:{port}{self.cfg.path}"
        ex = NbiExchange(request_type=REQUEST_TYPES[request_type], host=host, url=url,
                         body=body, started=time.time())
        t0 = time.perf_counter()
        conn = _VerifiedHTTPSConnection(
            host, port, context=self._ctx, server_name=self.cfg.tls_server_name or host,
            pin=self.cfg.cert_sha256, connect_timeout=self.cfg.connect_timeout_s,
            timeout=self.cfg.timeout_s)
        payload = json.dumps(body).encode("utf-8")
        try:
            conn.request("POST", self.cfg.path, body=payload, headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "wispr-portal",
            })
            resp = conn.getresponse()
            raw = resp.read(256 * 1024)
            ex.http_status = resp.status
            ex.tls = dict(conn.tls_info)
            if resp.status != 200:
                ex.error = NbiError("http", f"HTTP {resp.status}", host)
            else:
                try:
                    reply = json.loads(raw.decode("utf-8")) if raw else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    reply = None
                if not isinstance(reply, dict):
                    ex.error = NbiError("bad_reply", "reply is not a JSON object", host)
                else:
                    ex.reply = reply
        except ssl.SSLError as exc:            # includes certificate verification errors
            ex.error = NbiError("tls", str(exc), host)
        except (socket.timeout, TimeoutError) as exc:
            kind = "timeout" if conn.sock is not None else "connect"
            ex.error = NbiError(kind, f"timed out ({exc})", host)
        except (ConnectionError, OSError) as exc:
            kind = "connect" if conn.sock is None else "http"
            ex.error = NbiError(kind, str(exc) or exc.__class__.__name__, host)
        except http.client.HTTPException as exc:
            ex.error = NbiError("http", exc.__class__.__name__, host)
        finally:
            ex.tls = ex.tls or dict(conn.tls_info)
            conn.close()
            ex.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        return ex
