"""CSRF tokens, per-client rate limiting, reference IDs and response headers."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"   # no 0/O/1/I/L/U: easy to read aloud


def new_ref() -> str:
    """Reference ID shown to the guest and present on every log line of the visit."""
    chars = "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


def csrf_ok(expected: str | None, given: str | None) -> bool:
    return bool(expected) and bool(given) and hmac.compare_digest(expected, given)


class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client). In-process; with several workers
    each worker counts separately (the Dockerfile runs one worker)."""

    def __init__(self):
        self._hits: dict[tuple, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def allow(self, bucket: str, client: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep > 300:
                self._sweep(now, window_s)
            hits = self._hits[(bucket, client)]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def _sweep(self, now: float, window_s: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > window_s]:
            del self._hits[key]
        self._last_sweep = now


CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")


def apply_headers(response, is_https: bool, static: bool = False):
    h = response.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if static:
        h["Cache-Control"] = "public, max-age=3600"
    else:
        h["Cache-Control"] = "no-store"
        h["Pragma"] = "no-cache"
    if is_https:
        h["Strict-Transport-Security"] = "max-age=31536000"
    h.pop("Server", None)
    return response
