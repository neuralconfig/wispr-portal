"""The only two NBI operations the connector performs. Both are blocking (http.client) and run
in a thread pool. Events use the lab portal's JSON shapes (wispr.flow / wispr.events)."""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading

from wispr.events import utc_now_ms
from wispr.flow import Authorizer
from wispr.nbi import NbiClient

# Status for a fixed, locally administered dummy UE: proves TCP + TLS + NBI credentials without
# naming a real guest. A general Status, Logout, Disconnect or Decrypt is never forwarded.
PROBE_MAC = "02:00:00:00:00:00"

# A valid NBI reply that is not one of these means the node is up and accepts our credentials.
# 306 = wrong request password; 400/401 = controller/AAA errors.
PROBE_DOWN_CODES = {306, 400, 401}


class JsonlLog:
    """Local evidence log: one JSON object per line, rotated daily, kept 30 days."""

    def __init__(self, path: str | None):
        self._log = logging.getLogger(f"wispr-connector.jsonl.{id(self)}")
        self._log.propagate = False
        self._log.setLevel(logging.INFO)
        if path:
            h = logging.handlers.TimedRotatingFileHandler(path, when="midnight", backupCount=30,
                                                          encoding="utf-8", utc=True)
        else:
            h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        self._log.addHandler(h)
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        with self._lock:
            self._log.info(json.dumps(record, separators=(",", ":"), default=str))


class CollectingBus:
    """EventBus-compatible sink for one RPC: writes the full record locally and keeps the
    record for the reply to the cloud (the cloud strips bodies from its public stream)."""

    def __init__(self, log: JsonlLog, extra: dict | None = None):
        self.log = log
        self.extra = extra or {}
        self.events: list[dict] = []

    def emit(self, event: str, full: dict, public: dict | None = None) -> dict:
        record = {"ts": utc_now_ms(), "event": event, **full, **self.extra}
        self.log.write(record)
        self.events.append(record)
        return record


def probe(client: NbiClient, host: str, log: JsonlLog) -> dict:
    """Status for PROBE_MAC against exactly one host (no failover)."""
    if not client.allowed(host):
        return {"host": host, "reachable": False, "error_kind": "not_allowed", "error": "host not allowed"}
    body = client.build("status", {"client_mac": PROBE_MAC})
    ex = client.send("status", body, [host])
    result = {
        "host": host,
        "reachable": ex.error is None and ex.code is not None and ex.code not in PROBE_DOWN_CODES,
        "code": ex.code,
        "message": ex.message if ex.error is None else None,
        "http_status": ex.http_status,
        "duration_ms": ex.duration_ms,
        "tls": ex.tls,
        "error_kind": ex.error.kind if ex.error else None,
        "error": ex.error.detail if ex.error else None,
    }
    log.write({"ts": utc_now_ms(), "event": "nbi_probe", **result})
    return result


def accept(client: NbiClient, ref: str, params: dict, log: JsonlLog) -> dict:
    """The click-through authorization, exactly as the lab portal does it (Authorizer.accept).
    Returns the outcome plus the events it produced (nbi_request, nbi_response/nbi_error/
    nbi_not_allowed, auth_result), each with the connector's own timestamps and tls."""
    bus = CollectingBus(log, extra={"via": "connector"})
    auth = Authorizer(client, bus, mask_public=False, backend=client.cfg.backend)
    out = auth.accept(ref, params, status_checks=False)
    return {
        "outcome": out.kind,
        "ok": out.ok,
        "code": out.code,
        "message": out.message,
        "total_ms": out.total_ms,
        "nbi_calls": len(out.exchanges),
        "nbi_host": out.exchanges[-1].host if out.exchanges else None,
        "tls": out.exchanges[-1].tls if out.exchanges else {},
        "events": bus.events,
    }

