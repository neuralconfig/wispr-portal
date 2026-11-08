import { runInDurableObject, SELF } from "cloudflare:test";
import type { TenantHub } from "../src/hub/tenant-hub";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resetAllowCache } from "../src/guest/allow";
import fixture from "./fixtures/r3-portal-events.json";
import { connectFake, handshake, hubStub, LAB_IP, settle, T } from "./helpers";

// The redirect the R3 lab AP sent (fixture line 1), as a query string.
const golden = fixture.events;
const REDIRECT = new URLSearchParams({
  ...(golden[0].params as Record<string, string>),
  StartURL: (golden[0].params as Record<string, string>).startUrl,
});
REDIRECT.delete("startUrl");
const QUERY = REDIRECT.toString();
const AUTH = { Authorization: `Bearer ${T.TEST_EVENTS_TOKEN}` };

/** The connector's reply to accept, built from the fixture's NBI events (what wispr.flow emits). */
function connectorReply(ref: string, over: { outcome?: string; code?: number } = {}) {
  const pick = (name: string) => golden.find((e) => e.event === name) as Record<string, any>;
  const events: Record<string, any>[] = ["nbi_request", "nbi_response", "auth_result"].map((n) => ({ ...pick(n), ref, via: "connector" }));
  const outcome = over.outcome ?? "authorized";
  const auth = events[2];
  auth.outcome = outcome;
  if (over.code) auth.ResponseCode = events[1].ResponseCode = over.code;
  return {
    ok: true,
    result: { outcome, ok: outcome === "authorized", code: over.code ?? 201, message: "", total_ms: 566.6, nbi_calls: 1, events },
  };
}

function page(query = QUERY, ip = LAB_IP) {
  return SELF.fetch(`https://guest.test/?${query}`, { headers: { "CF-Connecting-IP": ip, "User-Agent": "vitest" } });
}

function form(html: string): { ref: string; csrf: string } {
  const ref = /name="ref" value="([^"]+)"/.exec(html)?.[1] ?? "";
  const csrf = /name="csrf" value="([^"]+)"/.exec(html)?.[1] ?? "";
  return { ref, csrf };
}

function post(body: Record<string, string>, ip = LAB_IP) {
  return SELF.fetch("https://guest.test/accept", {
    method: "POST",
    headers: { "CF-Connecting-IP": ip, "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body).toString(),
  });
}

async function events(query: string): Promise<any> {
  const res = await SELF.fetch(`https://api.test/v1/tenants/dha/events?${query}`, { headers: AUTH });
  expect(res.status).toBe(200);
  return res.json();
}

async function refEvents(ref: string): Promise<any[]> {
  return (await events(`ref=${ref}&limit=1000`)).events;
}

/** Read SSE frames until `until` says stop or the timeout passes. */
async function readFrames(res: Response, until: (frames: any[]) => boolean, timeoutMs = 2000) {
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  const frames: any[] = [];
  let buf = "";
  const deadline = Date.now() + timeoutMs;
  while (!until(frames) && Date.now() < deadline) {
    const r = await Promise.race([
      reader.read(),
      new Promise<{ done: true; value: undefined }>((ok) => setTimeout(() => ok({ done: true, value: undefined }), deadline - Date.now())),
    ]);
    if (r.done) break;
    buf += dec.decode(r.value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const id = /^id: (\d+)$/m.exec(chunk)?.[1];
      const data = /^data: (.*)$/m.exec(chunk)?.[1];
      if (data) frames.push({ id: Number(id), ...JSON.parse(data) });
      else if (/^retry:/m.test(chunk)) frames.push({ retry: chunk });
    }
  }
  await reader.cancel().catch(() => {});
  return frames;
}

let fake: Awaited<ReturnType<typeof connectFake>> | null = null;

type Accept = (args: any) => object | null | Promise<object | null>;

async function attach(accept?: Accept) {
  fake = await connectFake({ accept: accept ?? ((args) => connectorReply(args.ref)) });
  await handshake(fake);
  await settle();
  resetAllowCache();
  return fake;
}

beforeEach(() => resetAllowCache());
afterEach(async () => {
  fake?.ws?.close(1000, "test done");
  fake = null;
  await settle();
});

describe("guest flow", () => {
  it("terms → accept → success, with the lab's events in order and the golden key sets", async () => {
    const c = await attach();
    const res = await page();
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Security-Policy")).toContain("script-src 'self'");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const html = await res.text();
    expect(html.match(/<button[^>]*id="accept-button"/g)).toHaveLength(1);
    expect(html).toContain(`data-testid="accept"`);
    expect(html).toMatch(/Reference <span>[2-9A-Z]{4}-[2-9A-Z]{4}<\/span> · guest\.test · \d\d:\d\d UTC/);
    expect(html).not.toMatch(/https?:\/\/(?!www\.w3\.org)/); // R2: nothing off-host
    const { ref, csrf } = form(html);
    expect(ref).toMatch(/^[2-9A-Z]{4}-[2-9A-Z]{4}$/);

    const ok = await post({ ref, csrf });
    expect(ok.status).toBe(200);
    const done = await ok.text();
    expect(done).toContain(`id="ok-title"`);
    expect(done).toContain(`<meta http-equiv="refresh" content="10;url=https://www.health.mil/">`);
    expect(c.rpcs).toHaveLength(1);
    expect(c.rpcs[0].args).toEqual({
      ref,
      params: { client_mac: "02:AF:A2:20:A0:79", uip: "10.7.39.103", proxy: "0", nbiIP: "192.168.37.6" },
    });

    const got = await refEvents(ref);
    expect(got.map((e) => e.event)).toEqual(golden.map((e) => e.event));
    // Golden parity: same keys as the VM portal, except the documented differences.
    const ADDED = new Set(["seq", "client_ip_seen", "via", "connector_ms", "overhead_ms", "client_mac", "uip"]);
    const REMOVED = new Set(["body", "reply"]);
    got.forEach((e, i) => {
      const want = Object.keys(golden[i]).filter((k) => !REMOVED.has(k)).sort();
      const have = Object.keys(e).filter((k) => !ADDED.has(k) || k in golden[i]).sort();
      expect(have, e.event).toEqual(want);
      expect(e.ref).toBe(ref);
    });
    const byName = Object.fromEntries(got.map((e) => [e.event, e]));
    expect(byName.redirect_received).toMatchObject({
      mode: "customer",
      client: "10.7.39.103",
      client_ip_seen: LAB_IP,
      aliases: { startUrl: "StartURL" },
      params: golden[0].params,
    });
    expect(byName.terms_shown).toMatchObject({ facility: "Demo Medical Center", client_mac: "02:AF:A2:20:A0:79", uip: "10.7.39.103" });
    expect(byName.nbi_response.tls).toMatchObject({ version: "TLSv1.2", server_name: "scg.ruckuswireless.com" });
    expect(byName.auth_result).toMatchObject({ outcome: "authorized", total_ms: 566.6 });
    expect(byName.auth_result.connector_ms).toBeGreaterThanOrEqual(0);
    expect(byName.redirect_issued).toMatchObject({ target: "https://www.health.mil/", delay_s: 10 });
    expect(JSON.stringify(got)).not.toContain("RequestPassword");
  });

  it("a reload after success shows success again without a second Login; a double submit joins", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const c = await attach(async (args) => {
      await gate;
      return connectorReply(args.ref);
    });
    const { ref, csrf } = form(await (await page()).text());
    const first = post({ ref, csrf });
    const second = post({ ref, csrf });
    await settle();
    release();
    const [a, b] = await Promise.all([first, second]);
    expect([a.status, b.status]).toEqual([200, 200]);
    expect(c.rpcs).toHaveLength(1);
    const again = await post({ ref, csrf });
    expect(again.status).toBe(200);
    expect(await again.text()).toContain(`id="ok-title"`);
    expect(c.rpcs).toHaveLength(1);
    const names = (await refEvents(ref)).map((e) => e.event);
    expect(names.filter((n) => n === "accept_received")).toHaveLength(1);
    expect(names.filter((n) => n === "success_shown")).toHaveLength(2);
  });

  it("refuses a wrong token or an unknown ref with the expired page", async () => {
    await attach();
    const { ref } = form(await (await page()).text());
    const bad = await post({ ref, csrf: "nope" });
    expect(bad.status).toBe(403);
    const html = await bad.text();
    expect(html).toContain(`id="err-title"`);
    expect(html).toContain("This page has expired");
    expect(html).toContain(`href="/?${QUERY.replace(/&/g, "&#38;")}"`); // R10: try again from the original redirect
    expect((await post({ ref: "2222-2222", csrf: "x" })).status).toBe(403);
    expect((await post({})).status).toBe(403);
    expect((await refEvents(ref)).map((e) => e.event)).toContain("csrf_failed");
  });

  it("shows a friendly error with a retry link when the controller says no", async () => {
    await attach((args) => connectorReply(args.ref, { outcome: "login_failed", code: 302 }));
    const { ref, csrf } = form(await (await page()).text());
    const res = await post({ ref, csrf });
    expect(res.status).toBe(502);
    const html = await res.text();
    expect(html).toContain("We could not connect your device");
    expect(html).toContain("Try again");
    const got = await refEvents(ref);
    expect(got.map((e) => e.event).slice(-2)).toEqual(["auth_result", "error_shown"]);
    expect(got.at(-1)).toMatchObject({ kind: "login_failed", http_status: 502 });
  });

  it("fails fast when the connector is down, and on a disconnect mid-call never resends", async () => {
    await attach(() => null); // never replies
    let { ref, csrf } = form(await (await page()).text());
    const pending = post({ ref, csrf });
    await settle(100);
    fake!.ws!.close(1011, "gone");
    const lost = await pending;
    expect(lost.status).toBe(502);
    expect(await lost.text()).toContain("You may already be connected");
    fake = null;
    await settle();

    // Still allowlisted (the egress IP is remembered), but no connector to call.
    ({ ref, csrf } = form(await (await page()).text()));
    const down = await post({ ref, csrf });
    expect(down.status).toBe(502);
    expect(await down.text()).toContain("temporarily unavailable");
    expect((await refEvents(ref)).find((e) => e.event === "auth_result")).toMatchObject({ outcome: "connector_down" });
  });

  it("rejects bad redirect params with the bad_params page", async () => {
    await attach();
    const res = await page("uip=10.7.39.5");
    expect(res.status).toBe(400);
    const html = await res.text();
    expect(html).toContain("missing information from the Wi-Fi network");
    const ref = /<strong>([2-9A-Z]{4}-[2-9A-Z]{4})<\/strong>/.exec(html)![1];
    expect((await refEvents(ref)).map((e) => e.event)).toEqual(["redirect_received", "params_invalid", "error_shown"]);
  });

  it("limits accepts per client MAC (10/min)", async () => {
    await attach();
    const q = QUERY.replace("02%3AAF%3AA2%3A20%3AA0%3A79", "02:00:00:00:00:77");
    let status = 0;
    for (let i = 0; i < 11; i++) {
      const f = form(await (await page(q)).text());
      status = (await post(f)).status;
    }
    expect(status).toBe(429);
  });

  it("serves theme assets, keeps noise quiet, and gives other paths a ref", async () => {
    await attach();
    const css = await SELF.fetch("https://guest.test/static/css/customer.css", { headers: { "CF-Connecting-IP": LAB_IP } });
    expect(css.status).toBe(200);
    expect(css.headers.get("Content-Type")).toContain("text/css");
    expect(css.headers.get("Cache-Control")).toBe("public, max-age=3600");
    expect((await SELF.fetch("https://guest.test/static/js/debug.js", { headers: { "CF-Connecting-IP": LAB_IP } })).status).toBe(404);
    expect((await SELF.fetch("https://guest.test/static/css/customer.css", { headers: { "CF-Connecting-IP": "198.51.100.1" } })).status).toBe(403);
    const before = (await events("limit=1000")).events.length;
    expect((await SELF.fetch("https://guest.test/favicon.ico", { headers: { "CF-Connecting-IP": LAB_IP } })).status).toBe(404);
    expect((await events("limit=1000")).events.length).toBe(before);
    const nf = await SELF.fetch("https://guest.test/nope", { headers: { "CF-Connecting-IP": LAB_IP } });
    expect(nf.status).toBe(404);
    expect(await nf.text()).toContain("Page not found");
  });
});

describe("events API", () => {
  it("needs the events token", async () => {
    expect((await SELF.fetch("https://api.test/v1/tenants/dha/events")).status).toBe(401);
    expect((await SELF.fetch("https://api.test/v1/tenants/dha/events/stream")).status).toBe(401);
    expect((await SELF.fetch("https://api.test/v1/tenants/other/events", { headers: AUTH })).status).toBe(404);
    const bad = await SELF.fetch("https://api.test/v1/tenants/dha/events?since=yesterday", { headers: AUTH });
    expect(bad.status).toBe(400);
  });

  it("pages with a cursor", async () => {
    await attach();
    await page();
    const all = (await events("limit=1000")).events;
    expect(all.length).toBeGreaterThan(3);
    const p1 = await events("limit=2");
    expect(p1.events.map((e: any) => e.seq)).toEqual(all.slice(0, 2).map((e: any) => e.seq));
    const p2 = await events(`limit=2&cursor=${p1.next_cursor}`);
    expect(p2.events[0].seq).toBe(all[2].seq);
    const tail = await events(`cursor=${all.at(-1).seq}`);
    expect(tail).toEqual({ events: [], next_cursor: null, head_seq: expect.any(Number) });
    expect(tail.head_seq).toBeGreaterThanOrEqual(all.at(-1).seq);
  });

  it("streams live only by default, and replays from Last-Event-ID", async () => {
    await attach();
    await page(); // older events that a live-only stream must not show
    const live = await SELF.fetch("https://api.test/v1/tenants/dha/events/stream", { headers: AUTH });
    expect(live.status).toBe(200);
    expect(live.headers.get("Content-Type")).toContain("text/event-stream");
    const reading = readFrames(live, (f) => f.some((x) => x.event === "terms_shown"));
    await settle();
    const { ref } = form(await (await page()).text());
    const frames = await reading;
    // The instance (a comment, ignored by EventSource), then a Last-Event-ID even before any event.
    expect(frames[0].retry).toMatch(/^: instance=[0-9a-f]{8} booted_at=\S+Z\nretry: 3000\nid: \d+$/);
    const evs = frames.filter((f) => f.event);
    expect(evs.map((f) => f.event)).toEqual(["redirect_received", "terms_shown"]);
    expect(evs.every((f) => f.ref === ref)).toBe(true);
    expect(evs[1].id).toBe(evs[0].id + 1);

    const replay = await SELF.fetch("https://api.test/v1/tenants/dha/events/stream", {
      headers: { ...AUTH, "Last-Event-ID": String(evs[0].id - 1) },
    });
    const again = (await readFrames(replay, (f) => f.filter((x) => x.event).length >= 2)).filter((f) => f.event);
    expect(again.slice(0, 2).map((f) => f.id)).toEqual([evs[0].id, evs[1].id]);
  });

  it("marks open streams, and logs hub_started when a new instance finds another's streams were open", async () => {
    const marker = () =>
      runInDurableObject(hubStub(), (_h: TenantHub, state) =>
        state.storage.sql.exec<{ v: string }>(`SELECT v FROM kv WHERE k = 'streams_open'`).toArray()[0]?.v ?? null,
      );
    const res = await SELF.fetch("https://api.test/v1/tenants/dha/events/stream", { headers: AUTH });
    await readFrames(res, (f) => f.length >= 1); // reads the first frame, then cancels
    await settle();
    expect(await marker()).toBeNull(); // cancelled: the marker is cleared with the last stream
    const info = await runInDurableObject(hubStub(), (h: TenantHub) => h.hubInfo());
    expect(info.instance).toMatch(/^[0-9a-f]{8}$/);
    // A boot is quiet unless the marker names another instance (hibernation wakes are normal).
    await runInDurableObject(hubStub(), (h: TenantHub) => (h as any).noteBoot());
    expect((await events("limit=1000")).events.some((e: any) => e.event === "hub_started")).toBe(false);
    await runInDurableObject(hubStub(), (h: TenantHub, state) => {
      state.storage.sql.exec(`INSERT INTO kv (k, v) VALUES ('streams_open', ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v`,
        JSON.stringify({ instance: "deadbeef", count: 2, since: Date.parse("2026-11-08T22:00:00Z") }));
      (h as any).noteBoot();
    });
    const started = (await events("limit=1000")).events.filter((e: any) => e.event === "hub_started");
    expect(started).toHaveLength(1);
    expect(started[0]).toMatchObject({
      instance: info.instance,
      previous_instance: "deadbeef",
      streams_lost: 2,
      streams_open_since: "2026-11-08T22:00:00.000Z",
    });
    expect(await marker()).toBeNull();
    const health = await (await SELF.fetch("https://api.test/v1/tenants/dha/healthz", { headers: AUTH })).json<any>();
    expect(health.hub).toMatchObject({ instance: info.instance, head_seq: started[0].seq });
  });

  it("ends streams when the instance is stale (a deploy) or after 15 minutes, so clients reconnect", async () => {
    const open = () => SELF.fetch("https://api.test/v1/tenants/dha/events/stream", { headers: AUTH });
    const ended = async (res: Response) => {
      const reader = res.body!.getReader();
      for (;;) {
        const r = await Promise.race([reader.read(), settle(1000).then(() => "timeout" as const)]);
        if (r === "timeout") return false;
        if (r.done) return true;
      }
    };
    const a = await open();
    await settle();
    // Healthy tick: nothing closes.
    expect(await runInDurableObject(hubStub(), (h: TenantHub) => h.streamTick())).toEqual({ closed: 0, stale: false });
    // Another instance (the new version) appended an event this one never published.
    await runInDurableObject(hubStub(), (_h: TenantHub, state) => {
      state.storage.sql.exec(`INSERT INTO events (ts, ts_ms, ref, event, json) VALUES ('x', 0, NULL, 'probe', '{}')`);
    });
    expect(await runInDurableObject(hubStub(), (h: TenantHub) => h.streamTick())).toEqual({ closed: 1, stale: true });
    expect(await ended(a)).toBe(true);

    const b = await open();
    await settle();
    const r = await runInDurableObject(hubStub(), (h: TenantHub) => h.streamTick(Date.now() + 15 * 60_000));
    expect(r.closed).toBe(1);
    expect(await ended(b)).toBe(true);
  });
});
