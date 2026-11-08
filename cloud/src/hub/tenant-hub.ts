// TenantHub: one Durable Object per tenant. It holds the connector socket, pushes the NBI config,
// runs probes from an alarm, answers health and the guest allowlist (M-a), and runs the guest flow:
// visits, the accept RPC, the event log with its SSE stream and query (M-b). Protocol: connector/PROTOCOL.md.

import { DurableObject } from "cloudflare:workers";
import type { Env } from "../env";
import tenantConfig from "../../tenants/dha.json";
import { csrfOk, newCsrf, newRef, REF_RE } from "../guest/security";
import type { RedirectParams } from "../guest/params";
import { safeHttpUrl } from "../guest/params";

export const PING = '{"type":"ping"}';
export const PONG = '{"type":"pong"}';
const PROTOCOL = 1;
const RPC_TIMEOUT_MS = 30_000;
const PROBE_FRESH_MS = 120_000;
const EVENT_RETENTION_MS = 30 * 24 * 3600 * 1000;
const VISIT_RETENTION_MS = 24 * 3600 * 1000;
const DEBUG_RETENTION_MS = 7 * 24 * 3600 * 1000;
const IDLE_ALARM_MS = 3600 * 1000;
const MAX_STREAMS = 25;
const KEEPALIVE_MS = 15_000;
const QUERY_MAX = 1000;
// Fields kept out of the stream; masked copies go to debug_exchanges (plan: "Guest flow" step 2).
const STREAM_STRIP = ["body", "reply"];

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

/** What the Worker needs to render the page after a guest action. */
export interface PageResult {
  page: "terms" | "success" | "error";
  status: number;
  ref: string;
  csrf?: string;
  kind?: string;
  target?: string | null;
  delay?: number;
  retryUrl?: string | null;
}

export interface VisitInput {
  params: RedirectParams;
  query: string;
  userAgent: string;
  ipSeen: string;
}

interface Visit {
  ref: string;
  csrf: string;
  params: Record<string, string>;
  query: string;
  created_ms: number;
  state: "open" | "authorized";
  ip_seen: string;
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
  private streams = new Set<WritableStreamDefaultWriter<Uint8Array>>();
  private keepalive: ReturnType<typeof setInterval> | null = null;
  private inflight = new Map<string, Promise<PageResult>>();
  private hits = new Map<string, number[]>();

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
    this.sql.exec(`CREATE INDEX IF NOT EXISTS events_ref ON events (ref)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS visits (ref TEXT PRIMARY KEY, csrf TEXT NOT NULL, params TEXT NOT NULL,
      query TEXT NOT NULL, created_ms INTEGER NOT NULL, state TEXT NOT NULL, ip_seen TEXT NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS debug_exchanges (id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT,
      ts_ms INTEGER NOT NULL, json TEXT NOT NULL)`);
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

  /** Append one event (DO-stamped seq; ts is now unless the record brings its own) and publish it. */
  appendEvent(event: string, fields: Record<string, unknown>, ref: string | null = null, ts?: string): number {
    const ms = Date.now();
    const record = { ts: ts ?? nowIso(ms), event, ...(ref ? { ref } : {}), ...fields };
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
    this.publish(row.seq, record);
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
    if (url.pathname === "/events/stream") return this.openStream(request.headers.get("Last-Event-ID"));
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
        if (!this.sendConfig(ws)) {
          this.appendEvent("connector_error", { error: "SZ_NBI_PASSWORD secret is not set" });
          ws.send(JSON.stringify({ type: "config_unavailable" }));
          // A secret update does not drop a hibernated socket: retry from the alarm.
          await this.ctx.storage.setAlarm(Date.now() + 15_000);
        }
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

  /** Push the NBI config to a socket; false when the hub has no NBI password yet. */
  private sendConfig(ws: WebSocket): boolean {
    const config = this.nbiConfig();
    if (!config) return false;
    ws.send(JSON.stringify({ type: "config", config }));
    return true;
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
      // Sockets that said hello but have no config yet (e.g. the secret was missing): retry the push.
      for (const ws of this.sockets()) {
        const a = ws.deserializeAttachment() as Attachment | null;
        if (a?.hello && !a.applied && ws.readyState === WebSocket.OPEN) this.sendConfig(ws);
      }
      if (this.readySocket()) {
        for (const host of this.tenant.nbi.hosts) {
          await this.probeOne(host);
        }
      }
      this.sql.exec(`DELETE FROM events WHERE ts_ms < ?`, Date.now() - EVENT_RETENTION_MS);
      this.sql.exec(`DELETE FROM visits WHERE created_ms < ?`, Date.now() - VISIT_RETENTION_MS);
      this.sql.exec(`DELETE FROM debug_exchanges WHERE ts_ms < ?`, Date.now() - DEBUG_RETENTION_MS);
    } finally {
      // Probe while a connector is attached (a new connection re-arms it); otherwise only retention.
      const next = this.sockets().length > 0 ? this.tenant.probe_interval_s * 1000 : IDLE_ALARM_MS;
      await this.ctx.storage.setAlarm(Date.now() + next);
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
    const ws = this.readySocket() ?? this.sockets()[0] ?? null;
    const att = (ws?.deserializeAttachment() as Attachment | null) ?? null;
    const applied = this.kvGet("applied");
    return {
      httpStatus: h.ok ? 200 : 503,
      json: JSON.stringify({
        status: h.ok ? "ok" : "down",
        version,
        mode: "customer",
        backend: this.tenant.backend,
        // Which secrets are set (never their values): an unset guest password fails every Login.
        secrets: {
          nbi_password: !!this.env.SZ_NBI_PASSWORD,
          guest_password: !!this.env.SZ_GUEST_PASSWORD || this.tenant.nbi.auth_method !== "login",
        },
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

  // ---- guest flow (plan: "Guest flow") ---------------------------------------------------------
  private portal() {
    return this.tenant.portal;
  }

  /** Sliding one-minute window per key; in memory (a DO restart forgets it, which is fine). */
  private allow(key: string, perMin: number): boolean {
    const now = Date.now();
    const hits = (this.hits.get(key) ?? []).filter((t) => now - t < 60_000);
    if (hits.length >= perMin) {
      this.hits.set(key, hits);
      return false;
    }
    hits.push(now);
    this.hits.set(key, hits);
    if (this.hits.size > 5000) {
      for (const [k, v] of this.hits) if (!v.length || now - v[v.length - 1] >= 60_000) this.hits.delete(k);
    }
    return true;
  }

  /** Fields every guest-session event carries (R9): client = the guest's LAN IP (uip). */
  private session(params: Record<string, string>, ipSeen: string): Record<string, unknown> {
    return { mode: "customer", client: params.uip ?? null, client_ip_seen: ipSeen };
  }

  private ue(params: Record<string, string>): Record<string, unknown> {
    return { client_mac: params.client_mac ?? null, uip: params.uip ?? null };
  }

  private redirectTarget(params: Record<string, string>): string | null {
    const keys = this.portal().use_start_url ? ["startUrl", "url"] : ["url"];
    for (const k of keys) {
      const u = safeHttpUrl(params[k] ?? "");
      if (u) return u;
    }
    return this.portal().default_redirect_url || null;
  }

  private errorResult(
    ref: string,
    kind: string,
    status: number,
    base: Record<string, unknown>,
    retryUrl: string | null = null,
  ): PageResult {
    this.appendEvent("error_shown", { ...base, kind, http_status: status }, ref);
    return { page: "error", status, ref, kind, retryUrl };
  }

  /** GET /?…: record the redirect, store the visit, hand back ref + CSRF token for the terms page. */
  async openVisit(input: VisitInput): Promise<PageResult> {
    const p = input.params;
    const ref = newRef();
    const base = this.session(p.values, input.ipSeen);
    if (!this.allow(`page:${input.ipSeen}`, this.portal().rate_page_per_min)) {
      this.appendEvent("rate_limited", { ...base, bucket: "page" }, ref);
      return this.errorResult(ref, "rate_limited", 429, base);
    }
    this.appendEvent(
      "redirect_received",
      {
        ...base,
        params: p.values,
        unknown: p.unknown,
        rejected: p.rejected,
        missing: p.missing,
        aliases: p.aliases,
        user_agent: input.userAgent.slice(0, 300),
      },
      ref,
    );
    if (!p.ok) {
      this.appendEvent("params_invalid", { ...base, rejected: p.rejected, missing: p.missing }, ref);
      return this.errorResult(ref, "bad_params", 400, base);
    }
    const csrf = newCsrf();
    this.sql.exec(
      `INSERT INTO visits (ref, csrf, params, query, created_ms, state, ip_seen) VALUES (?, ?, ?, ?, ?, 'open', ?)`,
      ref,
      csrf,
      JSON.stringify(p.values),
      input.query.slice(0, 4096),
      Date.now(),
      input.ipSeen,
    );
    this.appendEvent("terms_shown", { ...base, facility: this.portal().facility, ...this.ue(p.values) }, ref);
    if ((await this.ctx.storage.getAlarm()) === null) await this.ctx.storage.setAlarm(Date.now() + IDLE_ALARM_MS);
    return { page: "terms", status: 200, ref, csrf };
  }

  private visit(ref: string): Visit | null {
    const row = this.sql
      .exec<{ ref: string; csrf: string; params: string; query: string; created_ms: number; state: string; ip_seen: string }>(
        `SELECT * FROM visits WHERE ref = ?`,
        ref,
      )
      .toArray()[0];
    return row ? { ...row, params: JSON.parse(row.params), state: row.state as Visit["state"] } : null;
  }

  /** POST /accept: check the token, then authorize through the connector (once per visit). */
  async accept(refIn: string, csrf: string, ipSeen: string): Promise<PageResult> {
    const known = REF_RE.test(refIn) ? this.visit(refIn) : null;
    const ref = known ? known.ref : newRef();
    const base = known ? this.session(known.params, ipSeen) : this.session({}, ipSeen);
    const retry = known ? `/?${known.query}` : null;
    const fresh = known !== null && Date.now() - known.created_ms <= this.portal().visit_ttl_s * 1000;
    if (!known || !fresh || !csrfOk(known.csrf, csrf)) {
      this.appendEvent("csrf_failed", { ...base, has_session: known !== null, expired: known !== null && !fresh }, ref);
      return this.errorResult(ref, "expired", 403, base, retry);
    }
    const v = known;
    // A reload or double submit after success shows success again, without a second Login.
    if (v.state === "authorized") {
      this.appendEvent("success_shown", { ...base, repeat: true, ...this.ue(v.params) }, ref);
      return this.successResult(v);
    }
    const running = this.inflight.get(ref);
    if (running) return running;
    if (!this.allow(`accept:${v.params.client_mac}`, this.portal().rate_accept_per_min)) {
      this.appendEvent("rate_limited", { ...base, bucket: "accept" }, ref);
      return this.errorResult(ref, "rate_limited", 429, base, retry);
    }
    const run = this.runAccept(v, base, retry).finally(() => this.inflight.delete(ref));
    this.inflight.set(ref, run);
    return run;
  }

  private successResult(v: Visit): PageResult {
    const target = this.redirectTarget(v.params);
    return { page: "success", status: 200, ref: v.ref, target, delay: this.portal().redirect_delay_s };
  }

  private async runAccept(v: Visit, base: Record<string, unknown>, retry: string | null): Promise<PageResult> {
    const ref = v.ref;
    const ue = this.ue(v.params);
    this.appendEvent("accept_received", { ...base, via: "form", ...ue }, ref);
    // Login needs the guest user's RADIUS password. Without the secret the connector would invent one
    // and RADIUS would log a failed login, so refuse here and say why.
    if (this.tenant.nbi.auth_method === "login" && !this.env.SZ_GUEST_PASSWORD) {
      this.appendEvent(
        "auth_result",
        { backend: this.tenant.backend, outcome: "portal_config", error: "SZ_GUEST_PASSWORD secret is not set", ...ue },
        ref,
      );
      return this.errorResult(ref, "portal_config", 502, base, retry);
    }
    const t0 = Date.now();
    let reply: RpcReply;
    try {
      reply = await this.rpc("accept", {
        ref,
        params: {
          client_mac: v.params.client_mac,
          uip: v.params.uip ?? "",
          proxy: v.params.proxy ?? "0",
          ...(v.params.nbiIP ? { nbiIP: v.params.nbiIP } : {}),
        },
      });
    } catch (e) {
      // Not connected: nothing was sent. Lost mid-call: the controller may have acted, so the
      // guest is told to try again (Login on an authorized client answers 101) and nothing is resent.
      const msg = (e as Error).message;
      const kind = msg === "connector not connected" ? "connector_down" : "connector_lost";
      this.appendEvent(
        "auth_result",
        { backend: this.tenant.backend, outcome: kind, error: msg, connector_ms: Date.now() - t0, ...ue },
        ref,
      );
      return this.errorResult(ref, kind, 502, base, retry);
    }
    const connectorMs = Date.now() - t0;
    if (!reply.ok) {
      this.appendEvent(
        "auth_result",
        {
          backend: this.tenant.backend,
          outcome: "not_allowed",
          error: `${reply.error ?? "error"}: ${String(reply.detail ?? "").slice(0, 200)}`,
          connector_ms: connectorMs,
          ...ue,
        },
        ref,
      );
      return this.errorResult(ref, "not_allowed", 502, base, retry);
    }
    const res = reply.result ?? {};
    for (const raw of Array.isArray(res.events) ? res.events : []) {
      if (!raw || typeof raw !== "object" || typeof raw.event !== "string") continue;
      const { ts, event, ref: _r, ...fields } = raw as Record<string, any>;
      if (STREAM_STRIP.some((k) => k in fields)) {
        this.sql.exec(`INSERT INTO debug_exchanges (ref, ts_ms, json) VALUES (?, ?, ?)`, ref, Date.now(), JSON.stringify(raw));
        for (const k of STREAM_STRIP) delete fields[k];
      }
      if (event === "auth_result") {
        fields.connector_ms = connectorMs;
        if (typeof fields.total_ms === "number") fields.overhead_ms = Math.round((connectorMs - fields.total_ms) * 10) / 10;
      }
      this.appendEvent(event, fields, ref, typeof ts === "string" ? ts : undefined);
    }
    if (!res.ok) {
      const kind = typeof res.outcome === "string" ? res.outcome : "controller";
      return this.errorResult(ref, kind, 502, base, retry);
    }
    this.sql.exec(`UPDATE visits SET state = 'authorized' WHERE ref = ?`, ref);
    v.state = "authorized";
    const out = this.successResult(v);
    this.appendEvent("success_shown", { ...base, outcome_ms: res.total_ms ?? null, ...ue }, ref);
    if (out.target) this.appendEvent("redirect_issued", { ...base, target: out.target, delay_s: out.delay }, ref);
    return out;
  }

  /** The ref shown on a page that has no visit (404s, server errors): logged so support can find it. */
  noteRef(kind: string, path: string, ipSeen: string): string {
    const ref = newRef();
    this.appendEvent("error_shown", { mode: "customer", client: null, client_ip_seen: ipSeen, kind, path: path.slice(0, 80) }, ref);
    return ref;
  }

  // ---- event stream and query (plan: "Events, stream, query, healthz") ------------------------------
  private publish(seq: number, record: Record<string, unknown>): void {
    if (!this.streams.size) return;
    const frame = new TextEncoder().encode(`id: ${seq}\ndata: ${JSON.stringify(record)}\n\n`);
    for (const w of this.streams) this.write(w, frame);
  }

  private write(w: WritableStreamDefaultWriter<Uint8Array>, chunk: Uint8Array): void {
    w.write(chunk).catch(() => this.dropStream(w));
  }

  private dropStream(w: WritableStreamDefaultWriter<Uint8Array>): void {
    if (!this.streams.delete(w)) return;
    w.abort().catch(() => {});
    if (!this.streams.size && this.keepalive) {
      clearInterval(this.keepalive);
      this.keepalive = null;
    }
  }

  /** SSE: live only, unless Last-Event-ID asks for a replay from that seq first. */
  private openStream(lastEventId: string | null): Response {
    if (this.streams.size >= MAX_STREAMS) {
      return new Response(JSON.stringify({ error: "too many event streams" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      });
    }
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
    const w = writable.getWriter();
    const enc = new TextEncoder();
    this.write(w, enc.encode("retry: 3000\n\n"));
    const from = lastEventId !== null && /^\d{1,15}$/.test(lastEventId.trim()) ? Number(lastEventId.trim()) : null;
    if (from !== null) {
      // Synchronous read + register: no event can land between the replay and going live.
      for (const r of this.sql.exec<{ seq: number; json: string }>(
        `SELECT seq, json FROM events WHERE seq > ? ORDER BY seq LIMIT 10000`,
        from,
      )) {
        this.write(w, enc.encode(`id: ${r.seq}\ndata: ${r.json}\n\n`));
      }
    }
    this.streams.add(w);
    w.closed.catch(() => {}).finally(() => this.dropStream(w));
    if (!this.keepalive) {
      this.keepalive = setInterval(() => {
        const beat = enc.encode(": keep-alive\n\n");
        for (const s of this.streams) this.write(s, beat);
      }, KEEPALIVE_MS);
    }
    return new Response(readable, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
      },
    });
  }

  /** GET …/events: ordered by seq, cursor = the last seq returned. since/until are ISO times (hub receive time). */
  queryEvents(q: { since?: string; until?: string; ref?: string; cursor?: string; limit?: string }): string {
    const where: string[] = [];
    const args: (string | number)[] = [];
    const time = (v: string | undefined, name: string) => {
      if (!v) return null;
      const ms = Date.parse(v);
      if (Number.isNaN(ms)) throw new Error(`${name}: expected an ISO 8601 time`);
      return ms;
    };
    try {
      const since = time(q.since, "since");
      const until = time(q.until, "until");
      if (since !== null) where.push("ts_ms >= ?"), args.push(since);
      if (until !== null) where.push("ts_ms < ?"), args.push(until);
      if (q.ref) {
        if (!REF_RE.test(q.ref)) throw new Error("ref: expected XXXX-XXXX");
        where.push("ref = ?"), args.push(q.ref);
      }
      if (q.cursor) {
        if (!/^\d{1,15}$/.test(q.cursor)) throw new Error("cursor: expected a number");
        where.push("seq > ?"), args.push(Number(q.cursor));
      }
    } catch (e) {
      return JSON.stringify({ error: (e as Error).message });
    }
    const limitRaw = q.limit ? Number(q.limit) : 100;
    const limit = Number.isInteger(limitRaw) && limitRaw > 0 ? Math.min(limitRaw, QUERY_MAX) : 100;
    const rows = this.sql
      .exec<{ seq: number; json: string }>(
        `SELECT seq, json FROM events ${where.length ? `WHERE ${where.join(" AND ")}` : ""} ORDER BY seq LIMIT ?`,
        ...args,
        limit + 1,
      )
      .toArray();
    const page = rows.slice(0, limit);
    return JSON.stringify({
      events: page.map((r) => ({ seq: r.seq, ...JSON.parse(r.json) })),
      next_cursor: rows.length > limit ? String(page[page.length - 1].seq) : null,
    });
  }

  /** Who may load guest pages: the connector's last-seen egress IP plus the tenant's static CIDRs. */
  allowlist(): string[] {
    const ip = this.kvGet("egress_ip");
    return [...(ip ? [ip] : []), ...this.tenant.egress_cidrs];
  }
}
