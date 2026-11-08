"""wispr-connector main loop: dial out over WSS, apply the cloud's NBI config, serve RPCs.

    python -m connector            (settings from the environment; see deploy/connector/)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import signal
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from wispr.config import ConfigError
from wispr.events import utc_now_ms
from wispr.nbi import NbiClient

from . import PROTOCOL, VERSION, ops
from .policy import PolicyError, RateLimiter, build_nbi_config, check_accept, describe
from .settings import Settings, load_settings

log = logging.getLogger("wispr-connector")

PING = '{"type":"ping"}'          # the hub answers with an auto-response, exact string match
PONG = '{"type":"pong"}'
FAMILIES = {"4": socket.AF_INET, "6": socket.AF_INET6, "any": socket.AF_UNSPEC}


class Connector:
    def __init__(self, settings: Settings):
        self.s = settings
        self.jsonl = ops.JsonlLog(settings.log_json_path)
        self.pool = ThreadPoolExecutor(max_workers=settings.max_concurrency, thread_name_prefix="nbi")
        self.limiter = RateLimiter(settings.max_nbi_per_min)
        self.client: NbiClient | None = None
        self.applied: dict | None = None
        self.ws: ClientConnection | None = None
        self.connected_since: str | None = None
        self.last_pong = 0.0
        self.last_probe: dict[str, dict] = {}
        self.stopping = asyncio.Event()

    # ---- state for /healthz -------------------------------------------------------------
    def health(self) -> tuple[int, dict]:
        up = self.ws is not None and self.client is not None
        body = {
            "status": "ok" if up else "down",
            "version": VERSION,
            "mode": "connector",
            "env": self.s.env_name,
            "backend": "smartzone",
            "nbi_hosts": list(self.applied["hosts"]) if self.applied else list(self.s.allowed_hosts),
            "wss_connected": self.ws is not None,
            "config_applied": self.client is not None,
            "connected_since": self.connected_since,
            "last_probe": self.last_probe,
        }
        return (200 if up else 503), body

    def event(self, event: str, **fields) -> None:
        self.jsonl.write({"ts": utc_now_ms(), "event": event, "env": self.s.env_name, **fields})

    # ---- the session ----------------------------------------------------------------------
    async def run(self) -> None:
        delay = 1.0
        while not self.stopping.is_set():
            started = time.monotonic()
            try:
                await self.session()
            except InvalidStatus as exc:
                code = exc.response.status_code
                self.event("connector_error", error=f"handshake rejected: HTTP {code}")
                if code in (401, 403):
                    delay = max(delay, 30.0)       # wrong token: don't hammer the edge
            except (OSError, ConnectionClosed, asyncio.TimeoutError) as exc:
                self.event("connector_error", error=f"{exc.__class__.__name__}: {exc}"[:300])
            except Exception as exc:               # keep the service alive; log and retry
                log.exception("session failed")
                self.event("connector_error", error=f"{exc.__class__.__name__}: {exc}"[:300])
            finally:
                self.ws = None
                self.connected_since = None
            if self.stopping.is_set():
                break
            if time.monotonic() - started > 60:
                delay = 1.0                        # the last session was healthy for a while
            sleep = min(delay, 30.0) * (0.5 + random.random() / 2)
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=sleep)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 30.0)

    async def session(self) -> None:
        headers = {"Authorization": f"Bearer {self.s.token}"}
        async with connect(self.s.url, additional_headers=headers, family=FAMILIES[self.s.ip_family],
                           user_agent_header=f"wispr-connector/{VERSION}", open_timeout=15,
                           ping_interval=None, close_timeout=5, max_size=1 << 20, compression=None) as ws:
            self.ws = ws
            self.connected_since = utc_now_ms()
            self.last_pong = time.monotonic()
            self.event("connector_connected", url=self.s.url)
            await ws.send(json.dumps({"type": "hello", "protocol": PROTOCOL, "version": VERSION,
                                      "env": self.s.env_name, "ceiling": self.s.ceiling()}))
            beat = asyncio.create_task(self.heartbeat(ws))
            tasks: set[asyncio.Task] = set()
            try:
                async for raw in ws:
                    if raw == PONG:
                        self.last_pong = time.monotonic()
                        continue
                    try:
                        msg = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(msg, dict):
                        continue
                    kind = msg.get("type")
                    if kind == "config":
                        await self.on_config(ws, msg.get("config"))
                    elif kind == "rpc":
                        t = asyncio.create_task(self.on_rpc(ws, msg))
                        tasks.add(t)
                        t.add_done_callback(tasks.discard)
                    elif kind == "pong":
                        self.last_pong = time.monotonic()
            finally:
                beat.cancel()
                self.event("connector_disconnected", code=ws.close_code, reason=ws.close_reason)

    async def heartbeat(self, ws: ClientConnection) -> None:
        while True:
            await asyncio.sleep(self.s.heartbeat_s)
            if time.monotonic() - self.last_pong > 3.5 * self.s.heartbeat_s:
                self.event("connector_error", error="heartbeat timeout")
                await ws.close(code=4000, reason="heartbeat timeout")
                return
            await ws.send(PING)

    async def on_config(self, ws: ClientConnection, cfg) -> None:
        try:
            nbi = build_nbi_config(cfg, self.s)
            client = NbiClient(nbi)                # builds the SSL context: a bad PEM fails here
            applied = describe(nbi)
        except (PolicyError, ConfigError, ValueError, OSError) as exc:
            self.client, self.applied = None, None
            self.event("config_rejected", error=str(exc)[:300])
            await ws.send(json.dumps({"type": "config_rejected", "error": str(exc)[:300]}))
            return
        self.client, self.applied = client, applied
        self.event("config_applied", **applied)
        await ws.send(json.dumps({"type": "config_applied", **applied}))

    async def on_rpc(self, ws: ClientConnection, msg: dict) -> None:
        rid, op, args = msg.get("id"), msg.get("op"), msg.get("args") or {}
        reply = {"type": "rpc_result", "id": rid}
        try:
            if self.client is None:
                raise PolicyError("no configuration applied")
            if op not in ("probe", "accept"):
                raise PolicyError(f"operation {str(op)[:40]!r} is not allowed")
            if not self.limiter.take():
                raise PolicyError("MAX_NBI_PER_MIN exceeded")
            loop = asyncio.get_running_loop()
            client = self.client
            if op == "probe":
                host = str(args.get("host", ""))
                result = await loop.run_in_executor(self.pool, ops.probe, client, host, self.jsonl)
                self.last_probe[host] = {k: result.get(k) for k in ("reachable", "code", "duration_ms", "error_kind")}
                self.last_probe[host]["checked_at"] = utc_now_ms()
            else:
                ref = str(args.get("ref", ""))[:20]
                params = check_accept(args.get("params"), self.s)
                result = await loop.run_in_executor(self.pool, ops.accept, client, ref, params, self.jsonl)
            reply.update(ok=True, result=result)
        except PolicyError as exc:
            self.event("rpc_refused", op=str(op)[:40], error=str(exc)[:300])
            reply.update(ok=False, error="policy", detail=str(exc)[:300])
        except Exception as exc:
            log.exception("rpc %s failed", op)
            reply.update(ok=False, error="internal", detail=f"{exc.__class__.__name__}"[:100])
        try:
            await ws.send(json.dumps(reply, default=str))
        except ConnectionClosed:
            pass                                    # the hub fails waiting callers itself

    # ---- local healthz ----------------------------------------------------------------------
    async def serve_healthz(self) -> asyncio.base_events.Server:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                line = await asyncio.wait_for(reader.readline(), 5)
                while (await asyncio.wait_for(reader.readline(), 5)) not in (b"\r\n", b"\n", b""):
                    pass
                parts = line.decode("latin-1").split()
                if len(parts) >= 2 and parts[0] in ("GET", "HEAD") and parts[1].split("?")[0] == "/healthz":
                    status, body = self.health()
                    payload = json.dumps(body).encode()
                else:
                    status, payload = 404, b'{"error":"not found"}'
                reason = {200: "OK", 404: "Not Found", 503: "Service Unavailable"}[status]
                head = (f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n")
                writer.write(head.encode() + (payload if parts[:1] != ["HEAD"] else b""))
                await writer.drain()
            except (asyncio.TimeoutError, ConnectionError, UnicodeDecodeError):
                pass
            finally:
                writer.close()

        return await asyncio.start_server(handle, self.s.healthz_host, self.s.healthz_port)


async def amain(settings: Settings) -> None:
    c = Connector(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, c.stopping.set)
        except NotImplementedError:
            pass
    server = await c.serve_healthz()
    runner = asyncio.create_task(c.run())
    await c.stopping.wait()
    if c.ws is not None:
        await c.ws.close(code=1001, reason="connector stopping")
    runner.cancel()
    server.close()
    c.pool.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    asyncio.run(amain(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
