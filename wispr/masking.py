"""Masking for anything that leaves the server log: pages, SSE events, API replies."""

from __future__ import annotations

import ipaddress
import re

SECRET_FIELDS = ("RequestPassword", "UE-Password")
UE_FIELDS = ("UE-MAC", "UE-IP")
MASK = "********"

_MAC_SPLIT = re.compile(r"[:.-]")


def mask_mac(value: str) -> str:
    """aa:bb:cc:dd:ee:ff -> **:**:**:**:ee:ff ; ENC... -> ENC1234…abcd"""
    if not value:
        return value
    if value.upper().startswith("ENC"):
        return mask_enc(value)
    hexdigits = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(hexdigits) != 12:
        return MASK
    sep = ":" if ":" in value else "-" if "-" in value else ""
    tail = [hexdigits[8:10], hexdigits[10:12]]
    if sep:
        return sep.join(["**"] * 4 + tail)
    return "*" * 8 + "".join(tail)


def mask_ip(value: str) -> str:
    """10.7.39.123 -> 10.7.39.* ; 2001:db8:1:2::5 -> 2001:db8:*:… ; ENC... -> ENC1234…abcd"""
    if not value:
        return value
    if value.upper().startswith("ENC"):
        return mask_enc(value)
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return MASK
    if ip.version == 4:
        return ".".join(value.split(".")[:3] + ["*"])
    groups = ip.exploded.split(":")
    return ":".join(groups[:2]) + ":*"


def mask_enc(value: str) -> str:
    if len(value) <= 13:
        return "ENC" + "*" * 4
    return f"{value[:7]}…{value[-4:]}"


def mask_body(body: dict, mask_ue: bool) -> dict:
    """Copy of an NBI request/response body with secrets (always) and UE ids (optionally) masked."""
    out = {}
    for key, val in body.items():
        if key in SECRET_FIELDS:
            out[key] = MASK
        elif mask_ue and key == "UE-MAC":
            out[key] = mask_mac(str(val))
        elif mask_ue and key == "UE-IP":
            out[key] = mask_ip(str(val))
        elif mask_ue and key == "Data":
            out[key] = MASK
        else:
            out[key] = val
    return out


def mask_params(values: dict, mask_ue: bool) -> dict:
    if not mask_ue:
        return dict(values)
    out = dict(values)
    if "client_mac" in out:
        out["client_mac"] = mask_mac(out["client_mac"])
    if "uip" in out:
        out["uip"] = mask_ip(out["uip"])
    return out
