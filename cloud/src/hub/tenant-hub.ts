// TenantHub: one Durable Object per tenant. In M-a it holds the connector socket, pushes the NBI
// config, runs probes from an alarm, records connector events, and answers health and the guest
// allowlist. The guest flow (visits, accept RPC, SSE) is added in M-b. Protocol: connector/PROTOCOL.md.

import { DurableObject } from "cloudflare:workers";
import type { Env } from "../env";
import tenantConfig from "../../tenants/dha.json";

export const PING = '{"type":"ping"}';
export const PONG = '{"type":"pong"}';
const PROTOCOL = 1;
const RPC_TIMEOUT_MS = 30_000;
const PROBE_FRESH_MS = 120_000;
const EVENT_RETENTION_MS = 30 * 24 * 3600 * 1000;

export type Tenant = typeof tenantConfig;

interface Attachment {
  egressIp: string;
  connectedAt: string;
  hello?: { version?: string; env?: string; ceiling?: unknown };
  applied?: Record<string, unknown>;
}

interface Probe {
  host: string;
  reachable: boolean;
  code: number | null;
  message: string | null;
  duration_ms: number | null;
  tls: Record<string, unknown> | null;
  error_kind: string | null;
  error: string | null;
  checked_at: string;
}

interface Pending {
  resolve: (v: RpcReply) => void;
  reject: (e: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface RpcReply {
  ok: boolean;
  result?: any;
  error?: string;
  detail?: string;
}

function nowIso(ms = Date.now()): string {
  return new Date(ms).toISOString();
}

export class TenantHub extends DurableObject<Env> {
  private sql: SqlStorage;
  private pending = new Map<string, Pending>();
  private nextId = 1;
  private tenant: Tenant = tenantConfig;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    // Local end-to-end runs (tools/cloud_e2e.py) point the tenant at a fake NBI. Dev only.
    if (env.ENVIRONMENT === "dev" && env.TENANT_OVERRIDE) {
      const o = JSON.parse(env.TENANT_OVERRIDE);
      this.tenant = { ...tenantConfig, ...o, nbi: { ...tenantConfig.nbi, ...(o.nbi ?? {}) } };
    }
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS probes (host TEXT PRIMARY KEY, json TEXT NOT NULL, checked_ms INTEGER NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
      ts_ms INTEGER NOT NULL, ref TEXT, event TEXT NOT NULL, json TEXT NOT NULL)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS events_ts ON events (ts_ms)`);
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair(PING, PONG));
  }

  // ---- small storage helpers ----------------------------------------------------------------
  private kvGet(k: string): string | null {
    const row = this.sql.exec<{ v: string }>(`SELECT v FROM kv WHERE k = ?`, k).toArray()[0];
    return row ? row.v : null;
  }

  private kvSet(k: string, v: string): void {
    this.sql.exec(`INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v`, k, v);
  }

  appendEvent(event: string, fields: Record<string, unknown>, ref: string | null = null): number {
    const ms = Date.now();
    const record = { ts: nowIso(ms), event, ...(ref ? { ref } : {}), ...fields };
    const row = this.sql
      .exec<{ seq: number }>(
        `INSERT INTO events (ts, ts_ms, ref, event, json) VALUES (?, ?, ?, ?, ?) RETURNING seq`,
        record.ts,
        ms,
        ref,
        event,
        JSON.stringify(record),
      )
      .one();
    return row.seq;
  }

  recentEvents(limit = 50): Record<string, unknown>[] {
    return this.sql
      .exec<{ seq: number; json: string }>(`SELECT seq, json FROM events ORDER BY seq DESC LIMIT ?`, limit)
      .toArray()
      .reverse()
      .map((r) => ({ seq: r.seq, ...JSON.parse(r.json) }));
  }

  // ---- connector socket ----------------------------------------------------------------------
  private sockets(): WebSocket[] {
    return this.ctx.getWebSockets("connector");
  }

  private readySocket(): WebSocket | null {
    for (const ws of this.sockets()) {
      const a = ws.deserializeAttachment() as Attachment | null;
      if (a?.applied && ws.readyState === WebSocket.OPEN) return ws;
    }
    return null;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== "/connect" || request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response("Not found", { status: 404 });
    }
    const egressIp = request.headers.get("X-Egress-IP") ?? "";
    // One connector per tenant in M-a: a new connection replaces the old one.
    for (const old of this.sockets()) {
      try {
        old.close(4001, "replaced by a newer connection");
      } catch {
        /* already closed */
      }
    }
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server, ["connector"]);
    const att: Attachment = { egressIp, connectedAt: nowIso() };
    server.serializeAttachment(att);
    if (egressIp) this.kvSet("egress_ip", egressIp);
    this.kvSet("connected_at", att.connectedAt);
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, raw: string | ArrayBuffer): Promise<void> {
    if (typeof raw !== "string") return;
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (!msg || typeof msg !== "object") return;
    const att = (ws.deserializeAttachment() as Attachment) ?? { egressIp: "", connectedAt: nowIso() };
    switch (msg.type) {
      case "hello": {
        att.hello = { version: String(msg.version ?? ""), env: String(msg.env ?? ""), ceiling: msg.ceiling };
        att.applied = undefined;
        ws.serializeAttachment(att);
        if (msg.protocol !== PROTOCOL) {
          this.appendEvent("connector_error", { error: `unsupported protocol ${String(msg.protocol)}` });
          ws.close(4002, "unsupported protocol");
          return;
        }
        const config = this.nbiConfig();
        if (!config) {
          this.appendEvent("connector_error", { error: "SZ_NBI_PASSWORD secret is not set" });
          ws.send(JSON.stringify({ type: "config_unavailable" }));
          return;
        }
        ws.send(JSON.stringify({ type: "config", config }));
        return;
      }
      case "config_applied": {
        const { type: _t, ...applied } = msg;
        att.applied = applied;
        ws.serializeAttachment(att);
        this.kvSet("applied", JSON.stringify(applied));
        this.kvSet("connector_version", att.hello?.version ?? "");
        this.appendEvent("connector_connected", {
          client_ip_seen: att.egressIp,
          connector_version: att.hello?.version ?? null,
          connector_env: att.hello?.env ?? null,
          ...applied,
        });
        await this.ctx.storage.setAlarm(Date.now() + 500);
        return;
      }
      case "config_rejected": {
        this.appendEvent("connector_error", { error: `config rejected: ${String(msg.error ?? "").slice(0, 300)}` });
        return;
      }
      case "rpc_result": {
        const p = this.pending.get(String(msg.id));
        if (!p) return;
        this.pending.delete(String(msg.id));
        clearTimeout(p.timer);
        p.resolve({ ok: !!msg.ok, result: msg.result, error: msg.error, detail: msg.detail });
        return;
      }
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    this.onSocketGone(ws, code, reason);
    try {
      ws.close(code === 1005 ? 1000 : code, reason);
    } catch {
      /* already closed */
    }
  }

  async webSocketError(ws: WebSocket, error: unknown): Promise<void> {
    this.onSocketGone(ws, 1011, String(error).slice(0, 120));
  }

  private onSocketGone(ws: WebSocket, code: number, reason: string): void {
    const att = ws.deserializeAttachment() as Attachment | null;
    this.kvSet("disconnected_at", String(Date.now()));
    this.appendEvent("connector_disconnected", {
      code,
      reason: reason.slice(0, 120),
      client_ip_seen: att?.egressIp ?? null,
    });
    // Callers waiting on this socket fail at once; a sent request is never resent elsewhere.
    if (!this.readySocket()) {
      for (const [id, p] of this.pending) {
        clearTimeout(p.timer);
        p.reject(new Error("connector disconnected"));
        this.pending.delete(id);
      }
    }
  }

  private nbiConfig(): Record<string, unknown> | null {
    if (!this.env.SZ_NBI_PASSWORD) return null;
    return {
      backend: this.tenant.backend,
      ...this.tenant.nbi,
      request_password: this.env.SZ_NBI_PASSWORD,
      guest_password: this.env.SZ_GUEST_PASSWORD ?? "",
    };
  }

  /** Send one RPC to the connector and wait for its reply. */
  async rpc(op: "probe" | "accept", args: Record<string, unknown>, timeoutMs = RPC_TIMEOUT_MS): Promise<RpcReply> {
    const ws = this.readySocket();
    if (!ws) throw new Error("connector not connected");
    const id = String(this.nextId++);
    const reply = new Promise<RpcReply>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("connector timeout"));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
    });
    ws.send(JSON.stringify({ type: "rpc", id, op, args }));
    return reply;
  }

  // ---- probes (alarm only, one at a time, never per request) -----------------------------------
  async alarm(): Promise<void> {
    try {
      if (this.readySocket()) {
        for (const host of this.tenant.nbi.hosts) {
          await this.probeOne(host);
        }
      }
      this.sql.exec(`DELETE FROM events WHERE ts_ms < ?`, Date.now() - EVENT_RETENTION_MS);
    } finally {
      // Keep probing while a connector is attached; a new connection re-arms the alarm.
      if (this.sockets().length > 0) {
        await this.ctx.storage.setAlarm(Date.now() + this.tenant.probe_interval_s * 1000);
      }
    }
  }

  private async probeOne(host: string): Promise<void> {
    let probe: Probe;
    try {
      const r = await this.rpc("probe", { host });
      const res = (r.ok ? r.result : null) ?? {};
      probe = {
        host,
        reachable: r.ok && res.reachable === true,
        code: typeof res.code === "number" ? res.code : null,
        message: res.message ?? null,
        duration_ms: typeof res.duration_ms === "number" ? res.duration_ms : null,
        tls: res.tls ?? null,
        error_kind: r.ok ? (res.error_kind ?? null) : (r.error ?? "error"),
        error: r.ok ? (res.error ?? null) : (r.detail ?? null),
        checked_at: nowIso(),
      };
    } catch (e) {
      probe = {
        host,
        reachable: false,
        code: null,
        message: null,
        duration_ms: null,
        tls: null,
        error_kind: "connector",
        error: (e as Error).message,
        checked_at: nowIso(),
      };
    }
    this.sql.exec(
      `INSERT INTO probes (host, json, checked_ms) VALUES (?, ?, ?)
       ON CONFLICT (host) DO UPDATE SET json = excluded.json, checked_ms = excluded.checked_ms`,
      host,
      JSON.stringify(probe),
      Date.now(),
    );
  }

  private probes(): Map<string, { probe: Probe; checkedMs: number }> {
    const out = new Map<string, { probe: Probe; checkedMs: number }>();
    for (const r of this.sql.exec<{ host: string; json: string; checked_ms: number }>(`SELECT * FROM probes`)) {
      out.set(r.host, { probe: JSON.parse(r.json), checkedMs: r.checked_ms });
    }
    return out;
  }

  // ---- health -------------------------------------------------------------------------------------
  private graceMs(): number {
    const override = Number(this.env.HEALTH_GRACE_S);
    return (Number.isFinite(override) && this.env.HEALTH_GRACE_S ? override : this.tenant.reconnect_grace_s) * 1000;
  }

  private healthCore() {
    const connected = this.readySocket() !== null;
    const disconnectedAt = Number(this.kvGet("disconnected_at") ?? 0);
    const inGrace = !connected && disconnectedAt > 0 && Date.now() - disconnectedAt < this.graceMs();
    const probes = this.probes();
    const nodes = this.tenant.nbi.hosts.map((host, i) => {
      const p = probes.get(host);
      const fresh = p !== undefined && Date.now() - p.checkedMs < PROBE_FRESH_MS;
      return { node: `node${i + 1}`, host, fresh, probe: p?.probe ?? null };
    });
    const usable = connected || inGrace;
    const anyReachable = usable && nodes.some((n) => n.fresh && n.probe?.reachable);
    return { connected, inGrace, nodes, ok: anyReachable };
  }

  /** Public /healthz: no IPs or timings (plan: "Events, stream, query, healthz"). */
  publicStatus(version: string): { httpStatus: number; json: string } {
    const h = this.healthCore();
    return {
      httpStatus: h.ok ? 200 : 503,
      json: JSON.stringify({
        status: h.ok ? "ok" : "down",
        version,
        mode: "customer",
        backend: this.tenant.backend,
        nbi_hosts: this.tenant.nbi.hosts.length,
        connector: { connected: h.connected },
        nbi: h.nodes.map((n) => ({
          node: n.node,
          reachable: !!(n.fresh && n.probe?.reachable && (h.connected || h.inGrace)),
          checked_at: n.probe?.checked_at ?? null,
        })),
      }),
    };
  }

  /** Token healthz: adds hosts, codes, timings, TLS and the connector details. */
  tokenStatus(version: string): { httpStatus: number; json: string } {
    const h = this.healthCore();
    const ws = this.readySocket();
    const att = (ws?.deserializeAttachment() as Attachment | null) ?? null;
    const applied = this.kvGet("applied");
    return {
      httpStatus: h.ok ? 200 : 503,
      json: JSON.stringify({
        status: h.ok ? "ok" : "down",
        version,
        mode: "customer",
        backend: this.tenant.backend,
        connector: {
          connected: h.connected,
          in_grace: h.inGrace,
          version: att?.hello?.version ?? this.kvGet("connector_version"),
          env: att?.hello?.env ?? null,
          ceiling: att?.hello?.ceiling ?? null,
          egress_ip: this.kvGet("egress_ip"),
          connected_at: att?.connectedAt ?? null,
          disconnected_at: this.kvGet("disconnected_at") ? nowIso(Number(this.kvGet("disconnected_at"))) : null,
          applied: applied ? JSON.parse(applied) : null,
        },
        nbi: h.nodes.map((n) => ({ node: n.node, host: n.host, fresh: n.fresh, ...(n.probe ?? {}) })),
        recent_events: this.recentEvents(20),
      }),
    };
  }

  /** Who may load guest pages: the connector's last-seen egress IP plus the tenant's static CIDRs. */
  allowlist(): string[] {
    const ip = this.kvGet("egress_ip");
    return [...(ip ? [ip] : []), ...this.tenant.egress_cidrs];
  }
}
