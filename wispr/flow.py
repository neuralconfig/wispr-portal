"""The click-through authorization flow, shared by debug and customer mode."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import nbi as N
from .events import EventBus
from .masking import mask_body, mask_ip, mask_mac
from .nbi import HostNotAllowed, NbiClient, NbiError, NbiExchange


@dataclass
class Outcome:
    kind: str                    # authorized | not_found | login_failed | portal_config |
                                 # controller | transport | not_allowed | pending_timeout
    code: int | None = None
    message: str = ""
    exchanges: list[NbiExchange] = field(default_factory=list)
    status_before: NbiExchange | None = None
    status_after: NbiExchange | None = None
    total_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.kind == "authorized"


FRIENDLY = {
    "not_found": ("We could not find your device on the guest network",
                  "Please check that you are still connected to the guest Wi-Fi network, then try again."),
    "login_failed": ("We could not connect your device",
                     "Please try again. If it keeps happening, disconnect from the guest Wi-Fi and reconnect."),
    "portal_config": ("Guest Wi-Fi sign-in is temporarily unavailable",
                      "Please try again in a few minutes."),
    "controller": ("Guest Wi-Fi sign-in is temporarily unavailable",
                   "Please try again in a few minutes."),
    "transport": ("Guest Wi-Fi sign-in is temporarily unavailable",
                  "Please try again in a few minutes."),
    "not_allowed": ("Guest Wi-Fi sign-in is temporarily unavailable",
                    "Please try again in a few minutes."),
    "pending_timeout": ("Connecting is taking longer than expected",
                        "Please wait a moment and try again."),
    "expired": ("This page has expired",
                "Please reload the page or reconnect to the guest Wi-Fi to start again."),
    "bad_params": ("This sign-in page is missing information from the Wi-Fi network",
                   "Please disconnect from the guest Wi-Fi, reconnect, and open any web page."),
    "rate_limited": ("Too many attempts",
                     "Please wait a minute, then try again."),
}


def classify(code: int | None, request_type: str) -> str:
    if code in N.AUTHORIZED:
        return "authorized"
    if request_type == "authorize" and code == 200:
        return "authorized"
    if code in N.PENDING:
        return "pending"
    if code in N.NOT_FOUND:
        return "not_found"
    if code in N.LOGIN_FAILED:
        return "login_failed"
    if code in N.PORTAL_CONFIG:
        return "portal_config"
    if code in N.CONTROLLER:
        return "controller"
    return "controller"


class Authorizer:
    def __init__(self, client: NbiClient, bus: EventBus, mask_public: bool, backend: str):
        self.client = client
        self.bus = bus
        self.mask_public = mask_public
        self.backend = backend

    # ---- logging helpers --------------------------------------------------------------
    def _ue(self, params) -> tuple[dict, dict]:
        full = {"client_mac": params.get("client_mac"), "uip": params.get("uip")}
        pub = {"client_mac": mask_mac(full["client_mac"]), "uip": mask_ip(full["uip"])} \
            if self.mask_public else dict(full)
        return full, pub

    def log_exchange(self, ref: str, ex: NbiExchange, params) -> None:
        full_ue, pub_ue = self._ue(params)
        common = {"ref": ref, "backend": self.backend, "request_type": ex.request_type,
                  "nbi_host": ex.host, "url": ex.url}
        self.bus.emit("nbi_request",
                      {**common, **full_ue, "body": mask_body(ex.body, mask_ue=False)},
                      {**common, **pub_ue, "body": mask_body(ex.body, mask_ue=self.mask_public)})
        if ex.error is not None:
            data = {**common, "error_kind": ex.error.kind, "error": ex.error.detail,
                    "http_status": ex.http_status, "duration_ms": ex.duration_ms, "tls": ex.tls}
            self.bus.emit("nbi_error", data, data)
            return
        reply = ex.reply or {}
        data = {**common, "http_status": ex.http_status, "ResponseCode": ex.code,
                "ReplyMessage": ex.message, "duration_ms": ex.duration_ms, "tls": ex.tls}
        self.bus.emit("nbi_response",
                      {**data, "reply": mask_body(reply, mask_ue=False)},
                      {**data, "reply": mask_body(reply, mask_ue=self.mask_public)})

    # ---- single calls -----------------------------------------------------------------
    def call(self, ref: str, request_type: str, params, data: str | None = None) -> NbiExchange:
        try:
            hosts = self.client.hosts_for(params.get("nbiIP") or None)
        except HostNotAllowed as exc:
            self.bus.emit("nbi_not_allowed", {"ref": ref, "nbiIP": params.get("nbiIP"),
                                              "allowlist": list(self.client.cfg.hosts)},
                          {"ref": ref, "nbiIP": params.get("nbiIP")})
            ex = NbiExchange(request_type=N.REQUEST_TYPES[request_type], host=exc.host or "",
                             url="", body={}, started=time.time(), error=exc)
            return ex
        body = self.client.build(request_type, params, data=data)
        ex = self.client.send(request_type, body, hosts)
        self.log_exchange(ref, ex, params)
        return ex

    # ---- the flow ---------------------------------------------------------------------
    def accept(self, ref: str, params, status_checks: bool = False) -> Outcome:
        """Authorize the guest after "I agree". ``status_checks`` adds Status before/after
        (debug mode); a 304 'Command not supported' there is recorded, not fatal."""
        t0 = time.perf_counter()
        out = Outcome(kind="controller")
        method = self.client.cfg.auth_method

        if status_checks:
            out.status_before = self.call(ref, "status", params)

        ex = self.call(ref, method, params)
        out.exchanges.append(ex)
        kind = self._kind(ex, method)

        if kind == "pending":
            deadline = time.monotonic() + self.client.cfg.async_max_s
            kind = "pending_timeout"
            while time.monotonic() < deadline:
                time.sleep(self.client.cfg.async_poll_s)
                st = self.call(ref, "status", params)
                out.exchanges.append(st)
                k = self._kind(st, "status")
                if k != "pending":
                    # Status answers 100 'unauthorized' after a failed login (guide p.39 note).
                    kind = "login_failed" if k == "login_failed" else k
                    break
            ex = out.exchanges[-1]

        out.kind = kind
        out.code = ex.code
        out.message = ex.message if ex.error is None else ex.error.detail

        if status_checks:
            out.status_after = self.call(ref, "status", params)
        out.total_ms = round((time.perf_counter() - t0) * 1000, 1)

        full_ue, pub_ue = self._ue(params)
        common = {"ref": ref, "backend": self.backend, "auth_method": method, "outcome": out.kind,
                  "ResponseCode": out.code, "ReplyMessage": out.message,
                  "nbi_calls": len(out.exchanges) + (2 if status_checks else 0),
                  "total_ms": out.total_ms}
        self.bus.emit("auth_result", {**common, **full_ue}, {**common, **pub_ue})
        return out

    @staticmethod
    def _kind(ex: NbiExchange, request_type: str) -> str:
        if ex.error is not None:
            return "not_allowed" if isinstance(ex.error, HostNotAllowed) else "transport"
        if ex.code is None:
            return "controller"
        return classify(ex.code, request_type)

    def decrypt(self, ref: str, params, value: str) -> str | None:
        ex = self.call(ref, "decrypt", params, data=value)
        if ex.error is None and ex.code == 200:
            data = (ex.reply or {}).get("Data")
            return str(data) if data is not None else None
        return None
