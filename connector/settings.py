"""Connector settings, read once from the environment (systemd EnvironmentFile).

The ALLOWED_* / GUEST_CIDRS / MAX_NBI_PER_MIN values are the local policy ceiling: the cloud
pushes the NBI configuration, but it can never widen these.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Mapping

from wispr.config import ConfigError, _float, _get, _int, _list, _secret

METHODS = ("login", "login_async", "authorize")


@dataclass(frozen=True)
class Settings:
    url: str
    token: str = field(repr=False)
    env_name: str
    allowed_hosts: tuple[str, ...]
    allowed_port: int
    allowed_methods: tuple[str, ...]
    guest_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    max_nbi_per_min: int
    local_ca_bundle: str | None
    ip_family: str                  # "4" | "6" | "any"
    healthz_host: str
    healthz_port: int
    log_json_path: str | None
    heartbeat_s: float
    max_concurrency: int

    def ceiling(self) -> dict:
        """What the connector reports in its hello (no secrets)."""
        return {
            "hosts": list(self.allowed_hosts),
            "port": self.allowed_port,
            "methods": list(self.allowed_methods),
            "guest_cidrs": [str(n) for n in self.guest_cidrs],
            "max_nbi_per_min": self.max_nbi_per_min,
        }


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    url = _get(env, "CONNECTOR_URL")
    if not url.startswith("wss://") and not (url.startswith("ws://") and _get(env, "CONNECTOR_ALLOW_PLAINTEXT") == "1"):
        raise ConfigError("CONNECTOR_URL: a wss:// URL is required, e.g. wss://guest-connector.lanpulse.com/v1/connect")
    token = _secret(env, "CONNECTOR_TOKEN")
    if not token:
        raise ConfigError("CONNECTOR_TOKEN(_FILE): the connector token is required")

    hosts = tuple(_list(env, "ALLOWED_NBI_HOSTS"))
    if not hosts:
        raise ConfigError("ALLOWED_NBI_HOSTS: the controller NBI addresses this connector may call, "
                          "e.g. 192.168.37.6,192.168.37.8")
    methods = tuple(_list(env, "ALLOWED_METHODS") or ["login", "authorize"])
    bad = [m for m in methods if m not in METHODS]
    if bad:
        raise ConfigError(f"ALLOWED_METHODS: unknown {', '.join(bad)} (allowed: {', '.join(METHODS)})")

    cidrs = []
    for raw in _list(env, "GUEST_CIDRS"):
        try:
            cidrs.append(ipaddress.ip_network(raw, strict=False))
        except ValueError as exc:
            raise ConfigError(f"GUEST_CIDRS: {raw!r} is not a network") from exc
    if not cidrs:
        raise ConfigError("GUEST_CIDRS: the guest subnets a UE-IP must be in, e.g. 10.7.39.0/24")

    ca = _get(env, "SZ_CA_BUNDLE") or None
    if ca and not os.path.isfile(ca):
        raise ConfigError(f"SZ_CA_BUNDLE: {ca} not found")

    family = _get(env, "CONNECTOR_IP_FAMILY", "4").lower()
    if family not in ("4", "6", "any"):
        raise ConfigError("CONNECTOR_IP_FAMILY: 4, 6 or any")

    listen = _get(env, "HEALTHZ_LISTEN", "127.0.0.1:9180")
    host, _, port = listen.rpartition(":")
    try:
        hport = int(port)
    except ValueError as exc:
        raise ConfigError(f"HEALTHZ_LISTEN: expected host:port, got {listen!r}") from exc

    return Settings(
        url=url,
        token=token,
        env_name=_get(env, "CONNECTOR_ENV", "production"),
        allowed_hosts=hosts,
        allowed_port=_int(env, "ALLOWED_NBI_PORT", 9443, 1, 65535),
        allowed_methods=methods,
        guest_cidrs=tuple(cidrs),
        max_nbi_per_min=_int(env, "MAX_NBI_PER_MIN", 120, 1, 6000),
        local_ca_bundle=ca,
        ip_family=family,
        healthz_host=host or "127.0.0.1",
        healthz_port=hport,
        log_json_path=_get(env, "LOG_JSON_PATH") or None,
        heartbeat_s=_float(env, "HEARTBEAT_S", 10.0, 1.0, 60.0),
        max_concurrency=_int(env, "MAX_CONCURRENCY", 8, 1, 64),
    )
