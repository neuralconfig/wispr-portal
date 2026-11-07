"""Deployment configuration, read once from the environment.

Every secret can be given either directly (``NAME``) or as a path to a file
(``NAME_FILE``, e.g. a Docker/Kubernetes secret mount). The file form wins.
Nothing in here is ever sent to the browser.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping


class ConfigError(ValueError):
    """Raised for a missing or invalid setting; the app refuses to start."""


def _get(env: Mapping[str, str], name: str, default: str = "") -> str:
    return env.get(name, default).strip()


def _secret(env: Mapping[str, str], name: str, default: str = "") -> str:
    path = _get(env, f"{name}_FILE")
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            raise ConfigError(f"{name}_FILE: cannot read {path}: {exc}") from exc
    return env.get(name, default).strip()


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(env, name)
    if not raw:
        return default
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}: expected true/false, got {raw!r}")


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = _get(env, name)
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: expected an integer, got {raw!r}") from exc
    if not lo <= val <= hi:
        raise ConfigError(f"{name}: {val} outside {lo}..{hi}")
    return val


def _float(env: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
    raw = _get(env, name)
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: expected a number, got {raw!r}") from exc
    if not lo <= val <= hi:
        raise ConfigError(f"{name}: {val} outside {lo}..{hi}")
    return val


def _list(env: Mapping[str, str], name: str) -> list[str]:
    return [x.strip().lower() for x in _get(env, name).split(",") if x.strip()]


def _read_text(env: Mapping[str, str], name: str) -> str | None:
    path = _get(env, name)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise ConfigError(f"{name}: cannot read {path}: {exc}") from exc


@dataclass(frozen=True)
class NbiConfig:
    """How the portal server reaches the controller's northbound interface."""

    backend: str                    # "smartzone" | "r1"
    hosts: tuple[str, ...]          # allowlist, lower-case host names / IPs
    port: int
    path: str
    vendor: str
    api_version: str
    request_username: str
    request_password: str = field(repr=False)
    auth_method: str                # "login" | "login_async" | "authorize"
    guest_username: str
    guest_password: str = field(repr=False)
    status_supported: bool
    timeout_s: float
    connect_timeout_s: float
    async_poll_s: float
    async_max_s: float
    ca_bundle: str | None
    tls_server_name: str | None
    cert_sha256: str | None         # hex, no colons, lower-case
    tls_max_version: str | None     # None | "1.2" | "1.3"


@dataclass(frozen=True)
class Config:
    mode: str                       # "debug" | "customer"
    nbi: NbiConfig
    secret_key: str = field(repr=False)
    secret_key_generated: bool
    facility_name: str
    welcome_text: str
    terms_text: str | None
    notice_text: str | None
    help_text: str
    agree_label: str
    logo_path: str | None
    logo_alt: str
    default_redirect_url: str
    redirect_delay_s: int
    use_start_url: bool
    events_token: str | None = field(repr=False)
    log_json_path: str | None
    log_console: bool
    log_decrypt_ue: bool
    rate_page_per_min: int
    rate_accept_per_min: int
    trust_proxy_hops: int
    session_ttl_s: int
    debug_status_checks: bool
    debug_decrypt: bool

    @property
    def is_debug(self) -> bool:
        return self.mode == "debug"


def _clean_fingerprint(raw: str) -> str | None:
    if not raw:
        return None
    fp = raw.replace(":", "").replace(" ", "").lower()
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        raise ConfigError("SZ_CERT_SHA256 / R1_CERT_SHA256: expected a SHA-256 hex fingerprint")
    return fp


def _nbi_config(env: Mapping[str, str], backend: str) -> NbiConfig:
    if backend == "smartzone":
        p = "SZ_"
        hosts = _list(env, "SZ_NBI_HOSTS")
        if not hosts:
            raise ConfigError("SZ_NBI_HOSTS: set the allowlist of controller NBI addresses "
                              "(comma separated), e.g. 192.168.37.6,192.168.37.8")
        port_default, vendor_default, user_default = 9443, "ruckus", ""
        method_default = "login"
        methods = ("login", "login_async", "authorize")
    else:
        p = "R1_"
        hosts = _list(env, "R1_NBI_HOSTS")
        if not hosts:
            raise ConfigError("R1_NBI_HOSTS: set the allowlist of RUCKUS One WISPr hosts, "
                              "e.g. <tenantid>.wispr.ruckus.cloud")
        port_default, vendor_default, user_default = 443, "Ruckus", "api"
        method_default = "authorize"
        methods = ("login", "authorize")

    password = _secret(env, f"{p}NBI_PASSWORD") if backend == "smartzone" else _secret(env, "R1_INTEGRATION_KEY")
    if not password:
        raise ConfigError(f"{'SZ_NBI_PASSWORD' if backend == 'smartzone' else 'R1_INTEGRATION_KEY'}"
                          "(_FILE): the NBI password is required")
    request_username = _secret(env, f"{p}NBI_USERNAME", user_default)
    if backend == "smartzone" and not request_username:
        raise ConfigError("SZ_NBI_USERNAME(_FILE): the WISPr NBI user name is required "
                          "(Administration > External Services > WISPr Northbound Interface)")

    method = _get(env, f"{p}AUTH_METHOD", method_default).lower()
    if method not in methods:
        raise ConfigError(f"{p}AUTH_METHOD: one of {', '.join(methods)}")
    if method == "login_async" and not _bool(env, f"{p}STATUS_SUPPORTED", False):
        raise ConfigError(f"{p}AUTH_METHOD=login_async polls with Status: set {p}STATUS_SUPPORTED=true")

    guest_password = _secret(env, f"{p}GUEST_PASSWORD")
    if not guest_password:
        # Only used for RequestType=Login. With an Always-Accept service any value works.
        guest_password = secrets.token_urlsafe(18)

    ca_bundle = _get(env, f"{p}CA_BUNDLE") or None
    if ca_bundle and not os.path.isfile(ca_bundle):
        raise ConfigError(f"{p}CA_BUNDLE: {ca_bundle} not found")

    tls_max = _get(env, f"{p}TLS_MAX_VERSION") or None
    if tls_max not in (None, "1.2", "1.3"):
        raise ConfigError(f"{p}TLS_MAX_VERSION: 1.2 or 1.3")

    path = _get(env, f"{p}NBI_PATH", "/portalintf")
    if not path.startswith("/"):
        raise ConfigError(f"{p}NBI_PATH must start with /")

    return NbiConfig(
        backend=backend,
        hosts=tuple(hosts),
        port=_int(env, f"{p}NBI_PORT", port_default, 1, 65535),
        path=path,
        vendor=_get(env, f"{p}VENDOR", vendor_default),
        api_version=_get(env, f"{p}API_VERSION", "1.0"),
        request_username=request_username,
        request_password=password,
        auth_method=method,
        guest_username=_get(env, f"{p}GUEST_USERNAME", "guest"),
        guest_password=guest_password,
        # SZ 7.0 guide p.39: Status "is only applicable to SZ100 and vSZ-E platforms";
        # the DHA lab is vSZ-H, so it is opt-in. Debug mode still probes it (DEBUG_STATUS_CHECKS).
        status_supported=_bool(env, f"{p}STATUS_SUPPORTED", False),
        # SZ: a Login waits for the SZ's own RADIUS exchange. Lab (7.1.1.3): 3 s x 5 tries to a dead
        # primary is ~15 s before the secondary is tried, so the default must be longer than that.
        timeout_s=_float(env, f"{p}NBI_TIMEOUT", 20.0 if backend == "smartzone" else 12.0, 1.0, 120.0),
        connect_timeout_s=_float(env, f"{p}NBI_CONNECT_TIMEOUT", 3.0, 0.5, 30.0),
        async_poll_s=_float(env, f"{p}ASYNC_POLL_INTERVAL", 1.0, 0.2, 10.0),
        async_max_s=_float(env, f"{p}ASYNC_MAX_WAIT", 15.0, 1.0, 120.0),
        ca_bundle=ca_bundle,
        tls_server_name=_get(env, f"{p}TLS_SERVER_NAME") or None,
        cert_sha256=_clean_fingerprint(_get(env, f"{p}CERT_SHA256")),
        tls_max_version=tls_max,
    )


DEFAULT_WELCOME = ("Free guest Wi-Fi is available to patients, visitors and families. "
                   "Please read the terms below and select “I agree” to connect.")
DEFAULT_HELP = "If you need help, please ask at the information desk."


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    mode = _get(env, "PORTAL_MODE", "customer").lower()
    if mode not in ("debug", "customer"):
        raise ConfigError("PORTAL_MODE: debug or customer")

    backend = _get(env, "PORTAL_BACKEND", "smartzone").lower()
    if backend in ("sz", "smartzone"):
        backend = "smartzone"
    elif backend in ("r1", "ruckusone", "ruckus-one"):
        backend = "r1"
    else:
        raise ConfigError("PORTAL_BACKEND: smartzone or r1")

    secret_key = _secret(env, "SECRET_KEY")
    generated = not secret_key
    if generated:
        secret_key = secrets.token_hex(32)
    elif len(secret_key) < 32:
        raise ConfigError("SECRET_KEY: use at least 32 characters")

    logo_path = _get(env, "LOGO_PATH") or None
    if logo_path and not os.path.isfile(logo_path):
        raise ConfigError(f"LOGO_PATH: {logo_path} not found")

    default_redirect = _get(env, "DEFAULT_REDIRECT_URL", "")
    if default_redirect and not default_redirect.lower().startswith(("http://", "https://")):
        raise ConfigError("DEFAULT_REDIRECT_URL must be an http(s) URL")

    is_debug = mode == "debug"
    return Config(
        mode=mode,
        nbi=_nbi_config(env, backend),
        secret_key=secret_key,
        secret_key_generated=generated,
        facility_name=_get(env, "FACILITY_NAME", "Demo Medical Center"),
        welcome_text=_get(env, "WELCOME_TEXT", DEFAULT_WELCOME),
        terms_text=_read_text(env, "TERMS_FILE"),
        notice_text=_read_text(env, "NOTICE_FILE"),
        help_text=_get(env, "HELP_TEXT", DEFAULT_HELP),
        agree_label=_get(env, "AGREE_LABEL", "I agree, connect me"),
        logo_path=logo_path,
        logo_alt=_get(env, "LOGO_ALT", ""),
        default_redirect_url=default_redirect,
        redirect_delay_s=_int(env, "REDIRECT_DELAY", 4, 0, 60),
        use_start_url=_bool(env, "USE_START_URL", True),
        events_token=_secret(env, "EVENTS_TOKEN") or None,
        log_json_path=_get(env, "LOG_JSON_PATH") or None,
        log_console=_bool(env, "LOG_CONSOLE", is_debug),
        log_decrypt_ue=_bool(env, "LOG_DECRYPT_UE", False),
        rate_page_per_min=_int(env, "RATE_PAGE_PER_MIN", 60, 1, 100000),
        rate_accept_per_min=_int(env, "RATE_ACCEPT_PER_MIN", 10, 1, 100000),
        trust_proxy_hops=_int(env, "TRUST_PROXY_HOPS", 0, 0, 5),
        session_ttl_s=_int(env, "SESSION_TTL", 1800, 60, 86400),
        debug_status_checks=_bool(env, "DEBUG_STATUS_CHECKS", True),
        debug_decrypt=_bool(env, "DEBUG_DECRYPT", True),
    )
