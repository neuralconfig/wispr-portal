"""Validation of the query string the controller appends to the portal URL.

Attribute list: SZ 7.0.0 Hotspot WISPr Interface Reference Guide, "Captive Portal
Attributes" Table 16 (p.53-54) and the R1 WISPr API reference "Redirection Attributes".
Every value is length-limited and checked against a strict pattern. Values that
fail are rejected (required ones) or dropped (optional ones) and recorded.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MAX_URL = 2048

_ENC = re.compile(r"^ENC[0-9A-Fa-f]{8,256}$")
_MAC = re.compile(
    r"^(?:[0-9A-Fa-f]{2}([:-]?)[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}"
    r"|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})$")
_HOST = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{1,63})*\.?$")
_TOKEN = re.compile(r"^[A-Za-z0-9._~:@%+=,/-]{1,256}$")
_REASON = re.compile(r"^[A-Za-z][A-Za-z-]{0,63}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def is_mac(value: str) -> bool:
    return bool(_MAC.match(value))


def is_enc(value: str) -> bool:
    return bool(_ENC.match(value))


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_host(value: str) -> bool:
    return is_ip(value) or bool(_HOST.match(value))


def normalize_host(raw: str) -> str | None:
    """Reduce an nbiIP value to a bare host. Accepts "1.2.3.4", "host",
    "https://host[:port]/portalintf" (R1 style) or "[v6]". Returns lower-case host or None."""
    value = raw.strip()
    if not value or len(value) > 300:
        return None
    if "://" in value:
        try:
            parts = urlsplit(value)
        except ValueError:
            return None
        if parts.scheme.lower() not in ("http", "https") or parts.username or parts.password:
            return None
        host = parts.hostname or ""
    else:
        host = value.split("/", 1)[0]
        if host.startswith("["):
            host = host[1:].split("]", 1)[0]
        elif host.count(":") == 1:          # host:port
            host = host.split(":", 1)[0]
    host = host.rstrip(".").lower()
    return host if is_host(host) else None


def safe_http_url(raw: str) -> str | None:
    """Return the URL if it is an absolute http(s) URL with a host, else None.
    Blocks javascript:, data:, protocol-relative and credential-bearing URLs."""
    value = raw.strip()
    if not value or len(value) > MAX_URL or _CTRL.search(value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return value


def _text(value: str, max_len: int) -> str | None:
    if len(value) > max_len or _CTRL.search(value):
        return None
    return value


def _int_range(lo: int, hi: int):
    def check(value: str) -> str | None:
        if not value.isdigit() or len(value) > 10:
            return None
        return value if lo <= int(value) <= hi else None
    return check


def _mac_or_enc(value: str) -> str | None:
    return value if (is_enc(value) or is_mac(value)) else None


def _ip_or_enc(value: str) -> str | None:
    return value if (is_enc(value) or is_ip(value)) else None


def _ip(value: str) -> str | None:
    return value if is_ip(value) else None


def _host(value: str) -> str | None:
    return value if normalize_host(value) else None


def _mac(value: str) -> str | None:
    return value if is_mac(value) else None


def _flag(value: str) -> str | None:
    return value if value in ("0", "1") else None


def _reason(value: str) -> str | None:
    return value if _REASON.match(value) else None


def _token(value: str) -> str | None:
    return value if _TOKEN.match(value) else None


# name -> (validator, description)
KNOWN: dict[str, tuple] = {
    "client_mac": (_mac_or_enc, "UE MAC (encrypted when the controller encrypts MAC/IP)"),
    "uip": (_ip_or_enc, "UE IP (encrypted when the controller encrypts MAC/IP)"),
    "nbiIP": (_host, "Controller NBI address (used only if it is in the allowlist)"),
    "nbiIPv6": (_ip, "Controller NBI IPv6 address"),
    "mac": (_mac, "AP MAC"),
    "apip": (_ip, "AP IP (ZD-style backup login)"),
    "ssid": (lambda v: _text(v, 32 * 4), "SSID"),
    "wlanName": (lambda v: _text(v, 128), "WLAN name"),
    "url": (safe_http_url, "Original URL the guest asked for"),
    "startUrl": (safe_http_url, "Start page from the portal profile"),
    "reason": (_reason, "Redirect reason (Un-Auth-Captive / Un-Auth-SSL-Captive)"),
    "proxy": (_flag, "Browser uses a web proxy"),
    "vlan": (_int_range(0, 4094), "Client VLAN"),
    "wlan": (_int_range(0, 1_000_000), "WLAN ID"),
    "sip": (_host, "Controller captive-portal FQDN"),
    "dn": (_host, "Domain name"),
    "zoneId": (_token, "Zone ID (3rd-party APs)"),
    "zoneName": (_token, "Opaque zone token (7.1.1.3: <token>_<epoch ms>)"),
    "lid": (lambda v: _text(v, 253), "Location ID"),
    "loc": (lambda v: _text(v, 253), "Location name"),
    "domain_name": (lambda v: _text(v, 128), "SZ management domain (seen on 7.1.1.3)"),
    "sshTunnelStatus": (_flag, "AP-to-controller tunnel up (1) or down (0)"),
}

REQUIRED = ("client_mac",)
MAX_UNKNOWN = 20

# Parameter names are matched case-insensitively. G70 Table 16 spells the start page
# "startUrl", but FIPS SZ 7.1.1.3 sends "StartURL" (lab, 2026-11-06).
_CANONICAL = {name.lower(): name for name in KNOWN}


@dataclass
class RedirectParams:
    values: dict[str, str] = field(default_factory=dict)       # accepted known params
    unknown: dict[str, str] = field(default_factory=dict)      # shown in debug only, never used
    rejected: dict[str, str] = field(default_factory=dict)     # name -> reason
    missing: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)      # canonical name -> spelling received

    @property
    def ok(self) -> bool:
        return not self.missing and not any(k in REQUIRED for k in self.rejected)

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    @property
    def mac_encrypted(self) -> bool:
        return is_enc(self.get("client_mac"))


def parse_redirect(args) -> RedirectParams:
    """``args`` is a mapping of name -> str or a werkzeug MultiDict."""
    result = RedirectParams()
    getlist = getattr(args, "getlist", None)
    for name in list(args.keys()):
        raw_list = getlist(name) if getlist else [args[name]]
        if len(raw_list) != 1:
            result.rejected[name] = "repeated parameter"
            continue
        raw = raw_list[0]
        canon = _CANONICAL.get(name.lower())
        if canon is not None and canon != name:
            result.aliases[canon] = name
            name = canon
        if name in result.values or name in result.rejected:   # e.g. startUrl and StartURL both sent
            result.values.pop(name, None)
            result.rejected[name] = "repeated parameter"
            continue
        if name not in KNOWN:
            if len(result.unknown) < MAX_UNKNOWN and len(name) <= 40:
                shown = _text(raw, 200)
                result.unknown[name[:40]] = shown if shown is not None else "(invalid)"
            continue
        validator = KNOWN[name][0]
        value = raw.strip()
        if not value:
            continue
        checked = validator(value)
        if checked is None:
            result.rejected[name] = "invalid format"
        else:
            result.values[name] = checked
    for name in REQUIRED:
        if name not in result.values and name not in result.rejected:
            result.missing.append(name)
    return result
