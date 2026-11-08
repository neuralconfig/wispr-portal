"""The local policy ceiling: what the cloud may configure and ask for.

The cloud pushes the NBI configuration (hosts, port, credentials, TLS trust). Everything it pushes
is checked against Settings; anything outside the ceiling is refused, never clamped silently.
"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import deque

from wispr.config import NbiConfig
from wispr.params import normalize_host

from .settings import Settings


class PolicyError(ValueError):
    """The cloud asked for something outside the local ceiling."""


def _fingerprint(raw: str | None) -> str | None:
    if not raw:
        return None
    fp = raw.replace(":", "").replace(" ", "").lower()
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        raise PolicyError("cert_sha256: expected a SHA-256 hex fingerprint")
    return fp


def _num(cfg: dict, key: str, default: float, lo: float, hi: float) -> float:
    val = cfg.get(key, default)
    if not isinstance(val, (int, float)) or isinstance(val, bool) or not lo <= val <= hi:
        raise PolicyError(f"{key}: expected a number in {lo}..{hi}")
    return float(val)


def _str(cfg: dict, key: str, default: str = "") -> str:
    val = cfg.get(key, default)
    if val is None:
        return default
    if not isinstance(val, str):
        raise PolicyError(f"{key}: expected a string")
    return val


def build_nbi_config(cfg: dict, settings: Settings) -> NbiConfig:
    """Validate the cloud's config message against the ceiling and build an NbiConfig."""
    if not isinstance(cfg, dict):
        raise PolicyError("config: expected an object")
    backend = _str(cfg, "backend", "smartzone")
    if backend != "smartzone":
        raise PolicyError("backend: this connector only serves smartzone")

    raw_hosts = cfg.get("hosts")
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise PolicyError("hosts: expected a non-empty list")
    hosts = []
    for h in raw_hosts:
        host = normalize_host(h) if isinstance(h, str) else None
        if not host or host not in settings.allowed_hosts:
            raise PolicyError(f"hosts: {str(h)[:80]!r} is not in ALLOWED_NBI_HOSTS")
        if host not in hosts:
            hosts.append(host)

    port = cfg.get("port", settings.allowed_port)
    if port != settings.allowed_port:
        raise PolicyError(f"port: {port!r} is not ALLOWED_NBI_PORT ({settings.allowed_port})")

    method = _str(cfg, "auth_method", "login").lower()
    if method not in settings.allowed_methods:
        raise PolicyError(f"auth_method: {method!r} is not in ALLOWED_METHODS")
    status_supported = bool(cfg.get("status_supported", False))
    if method == "login_async" and not status_supported:
        raise PolicyError("auth_method login_async needs status_supported")

    path = _str(cfg, "path", "/portalintf")
    if not path.startswith("/") or len(path) > 100:
        raise PolicyError("path: must start with /")

    request_password = _str(cfg, "request_password")
    request_username = _str(cfg, "request_username")
    if not request_password or not request_username:
        raise PolicyError("request_username/request_password: required")

    tls_max = cfg.get("tls_max_version")
    if tls_max not in (None, "1.2", "1.3"):
        raise PolicyError("tls_max_version: 1.2, 1.3 or null")

    ca_pem = cfg.get("ca_pem") or None
    if ca_pem is not None and (not isinstance(ca_pem, str) or "-----BEGIN CERTIFICATE-----" not in ca_pem):
        raise PolicyError("ca_pem: expected PEM certificate text")
    if ca_pem is None and settings.local_ca_bundle is None:
        raise PolicyError("no trust anchor: the cloud sent no ca_pem and SZ_CA_BUNDLE is not set "
                          "(the system store is never used for the NBI)")

    return NbiConfig(
        backend="smartzone",
        hosts=tuple(hosts),
        port=settings.allowed_port,
        path=path,
        vendor=_str(cfg, "vendor", "ruckus"),
        api_version=_str(cfg, "api_version", "1.0"),
        request_username=request_username,
        request_password=request_password,
        auth_method=method,
        guest_username=_str(cfg, "guest_username", "guest"),
        guest_password=_str(cfg, "guest_password") or _random_password(),
        status_supported=status_supported,
        timeout_s=_num(cfg, "timeout_s", 20.0, 1.0, 120.0),
        connect_timeout_s=_num(cfg, "connect_timeout_s", 3.0, 0.5, 30.0),
        async_poll_s=_num(cfg, "async_poll_s", 1.0, 0.2, 10.0),
        async_max_s=_num(cfg, "async_max_s", 15.0, 1.0, 120.0),
        ca_bundle=None if ca_pem else settings.local_ca_bundle,
        tls_server_name=_str(cfg, "tls_server_name") or None,
        cert_sha256=_fingerprint(_str(cfg, "cert_sha256")),
        tls_max_version=tls_max,
        ca_pem=ca_pem,
    )


def _random_password() -> str:
    import secrets
    return secrets.token_urlsafe(18)


def describe(nbi: NbiConfig) -> dict:
    """What the connector actually applied (reported back to the cloud; no secrets)."""
    if nbi.ca_pem:
        ca_source, ca_sha = "cloud", hashlib.sha256(nbi.ca_pem.encode()).hexdigest()
    else:
        with open(nbi.ca_bundle, "rb") as fh:          # validated to exist by load_settings
            ca_source, ca_sha = "local", hashlib.sha256(fh.read()).hexdigest()
    return {"hosts": list(nbi.hosts), "port": nbi.port, "auth_method": nbi.auth_method,
            "server_name": nbi.tls_server_name, "pin": nbi.cert_sha256, "ca_source": ca_source,
            "ca_sha256": ca_sha, "tls_max_version": nbi.tls_max_version}


def check_accept(params: dict, settings: Settings) -> dict:
    """Validate the accept arguments: UE-IP must be a clear address inside GUEST_CIDRS."""
    if not isinstance(params, dict):
        raise PolicyError("params: expected an object")
    out = {}
    for key in ("client_mac", "uip", "proxy", "nbiIP"):
        val = params.get(key)
        if val is not None and (not isinstance(val, str) or len(val) > 200):
            raise PolicyError(f"{key}: expected a short string")
        if val:
            out[key] = val
    if not out.get("client_mac"):
        raise PolicyError("client_mac: required")
    try:
        ip = ipaddress.ip_address(out.get("uip", ""))
    except ValueError as exc:
        raise PolicyError("uip: must be a clear IP address in GUEST_CIDRS") from exc
    if not any(ip in net for net in settings.guest_cidrs):
        raise PolicyError("uip: not in GUEST_CIDRS")
    return out


class RateLimiter:
    """Sliding one-minute window over every NBI operation (MAX_NBI_PER_MIN)."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] > 60:
                self._times.popleft()
            if len(self._times) >= self.per_min:
                return False
            self._times.append(now)
            return True
