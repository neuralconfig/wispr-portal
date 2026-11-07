"""Evidence trail: JSON-lines log (full values, server side only), a colour console log,
and an in-process pub/sub that feeds the /events SSE stream (masked in customer mode)."""

from __future__ import annotations

import json
import queue
import sys
import threading
from collections import deque
from datetime import datetime, timezone

_COLOURS = {
    "redirect_received": "\033[96m", "terms_shown": "\033[96m", "debug_shown": "\033[96m",
    "accept_received": "\033[94m", "nbi_request": "\033[93m", "nbi_response": "\033[92m",
    "nbi_error": "\033[91m", "auth_result": "\033[95m", "redirect_issued": "\033[95m",
    "success_shown": "\033[92m", "error_shown": "\033[91m", "params_invalid": "\033[91m",
    "csrf_failed": "\033[91m", "rate_limited": "\033[91m", "nbi_not_allowed": "\033[91m",
    "startup": "\033[1m\033[92m",
}
_RESET = "\033[0m"


def utc_from_epoch_ms(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventBus:
    def __init__(self, json_path: str | None, console: bool, history: int = 200,
                 max_subscribers: int = 25):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._history: deque = deque(maxlen=history)
        self._max_subs = max_subscribers
        self._console = console
        self._json_fh = open(json_path, "a", encoding="utf-8", buffering=1) if json_path else None

    # ---- emit -------------------------------------------------------------------------
    def emit(self, event: str, full: dict, public: dict | None = None) -> dict:
        """``full`` goes to the server log; ``public`` (already masked by the caller, or the
        same dict in debug mode) goes to SSE subscribers."""
        record = {"ts": utc_now_ms(), "event": event, **full}
        line = json.dumps(record, separators=(",", ":"), default=str)
        with self._lock:
            out = self._json_fh or sys.stdout
            out.write(line + "\n")
            out.flush()
            if self._console:
                self._console_line(record)
            pub = {"ts": record["ts"], "event": event, **(public if public is not None else full)}
            self._history.append(pub)
            for q in list(self._subs):
                try:
                    q.put_nowait(pub)
                except queue.Full:
                    pass
        return record

    def _console_line(self, rec: dict) -> None:
        colour = _COLOURS.get(rec["event"], "")
        extras = {k: v for k, v in rec.items() if k not in ("ts", "event")}
        text = json.dumps(extras, default=str, indent=2) if rec["event"].startswith("nbi_") else \
            " ".join(f"{k}={v}" for k, v in extras.items() if not isinstance(v, (dict, list)))
        sys.stderr.write(f"{colour}[{rec['ts']}] {rec['event'].upper()}{_RESET} {colour}{text}{_RESET}\n")
        sys.stderr.flush()

    # ---- subscribe --------------------------------------------------------------------
    def subscribe(self) -> queue.Queue | None:
        with self._lock:
            if len(self._subs) >= self._max_subs:
                return None
            q: queue.Queue = queue.Queue(maxsize=500)
            for item in self._history:
                q.put_nowait(item)
            self._subs.append(q)
            return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._history)
