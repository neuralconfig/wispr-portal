import { runDurableObjectAlarm, SELF } from "cloudflare:test";
import { connectFake, handshake, hubStub, LAB_IP, settle, T } from "./helpers";
import { beforeEach, describe, expect, it } from "vitest";
import { resetAllowCache } from "../src/guest/allow";
import { newRef } from "../src/guest/security";
import { ipAllowed } from "../src/net";

beforeEach(() => resetAllowCache());

describe("connector endpoint", () => {
  it("requires a WebSocket upgrade and the right token", async () => {
    expect((await SELF.fetch("https://connector.test/v1/connect")).status).toBe(426);
    expect((await connectFake({ token: "wpc_dha_wrongtoken000000000" })).res.status).toBe(401);
    const noAuth = await SELF.fetch("https://connector.test/v1/connect", { headers: { Upgrade: "websocket" } });
    expect(noAuth.status).toBe(401);
  });

  it("pushes the NBI config with the secret password on hello", async () => {
    const c = await connectFake();
    expect(c.res.status).toBe(101);
    const config = await handshake(c);
    expect(config.type).toBe("config");
    expect(config.config).toMatchObject({
      hosts: ["192.168.37.6", "192.168.37.8"],
      port: 9443,
      request_username: "dha-nbi",
      request_password: "nbi-secret-test",
      guest_password: "guest-secret-test",
      tls_server_name: "scg.ruckuswireless.com",
      guest_username: "dha-guest",
    });
    c.ws!.close(1000, "done");
  });

  it("re-pushes the config only when it changed", async () => {
    const c = await connectFake();
    await handshake(c);
    await settle();
    expect(await runDurableObjectAlarm(hubStub())).toBe(true);
    await settle();
    expect(c.received.filter((m) => m.type === "config")).toHaveLength(0);
    c.ws!.close(1000, "done");
  });

  it("refuses an unknown protocol version", async () => {
    const c = await connectFake();
    const closed = new Promise<number>((r) => c.ws!.addEventListener("close", (e) => r(e.code)));
    c.ws!.send(JSON.stringify({ type: "hello", protocol: 99 }));
    expect(await closed).toBe(4002);
  });
});

describe("probes and health", () => {
  it("reports down before any connector, ok after a probe, down after disconnect", async () => {
    let res = await SELF.fetch("https://guest.test/healthz");
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ status: "down", connector: { connected: false } });

    const c = await connectFake({ probe: (h) => (h === "192.168.37.6" ? { reachable: true, code: 100 } : { reachable: false, error_kind: "connect" }) });
    await handshake(c);
    await settle();
    expect(await runDurableObjectAlarm(hubStub())).toBe(true);

    res = await SELF.fetch("https://guest.test/healthz");
    expect(res.status).toBe(200);
    const body: any = await res.json();
    expect(body).toMatchObject({ status: "ok", nbi_hosts: 2, connector: { connected: true } });
    expect(body.nbi.map((n: any) => [n.node, n.reachable])).toEqual([["node1", true], ["node2", false]]);
    expect(JSON.stringify(body)).not.toContain("192.168");          // no IPs in the public healthz

    // token healthz: details, only with the events token
    expect((await SELF.fetch("https://api.test/v1/tenants/dha/healthz")).status).toBe(401);
    res = await SELF.fetch("https://api.test/v1/tenants/dha/healthz", {
      headers: { Authorization: `Bearer ${T.TEST_EVENTS_TOKEN}` },
    });
    const detail: any = await res.json();
    expect(detail.connector).toMatchObject({ connected: true, egress_ip: LAB_IP, version: "0.1.0" });
    expect(detail.nbi[0]).toMatchObject({ host: "192.168.37.6", code: 100, reachable: true });
    expect(detail.recent_events.map((e: any) => e.event)).toContain("connector_connected");
    expect(JSON.stringify(detail)).not.toContain("nbi-secret-test");

    c.ws!.close(1000, "bye");
    await settle();
    res = await SELF.fetch("https://guest.test/healthz");
    expect(res.status).toBe(503);
  });
});

describe("guest allowlist", () => {
  it("serves guest pages only to the connector's egress IP; healthz stays open", async () => {
    const page = (ip: string) =>
      SELF.fetch("https://guest.test/?client_mac=AA:BB:CC:00:11:22&uip=10.7.39.5", { headers: { "CF-Connecting-IP": ip } });
    // Storage is shared across this file, so use an address no connector has used.
    expect((await page("198.51.100.7")).status).toBe(403);

    const c = await connectFake({ ip: LAB_IP });
    await handshake(c);
    await settle();
    resetAllowCache();
    const ok = await page(LAB_IP);
    expect(ok.status).toBe(200);
    expect(await ok.text()).toContain(`id="accept-button" data-testid="accept"`);
    expect((await page("203.0.113.9")).status).toBe(403);
    expect((await SELF.fetch("https://guest.test/healthz", { headers: { "CF-Connecting-IP": "203.0.113.9" } })).status).not.toBe(403);

    // The ISP changes the NAT IP: the reconnecting connector moves the allowlist with it.
    c.ws!.close(1000, "moving");
    const c2 = await connectFake({ ip: "70.40.100.80" });
    await handshake(c2);
    await settle();
    expect((await page("70.40.100.80")).status).toBe(200);          // re-read on miss, no cache wait
    resetAllowCache();
    expect((await page(LAB_IP)).status).toBe(403);
    c2.ws!.close(1000, "done");
  });
});

describe("routing and helpers", () => {
  it("rejects other methods, hosts and upgrades outside the connector host", async () => {
    expect((await SELF.fetch("https://guest.test/", { method: "POST" })).status).toBe(405);
    expect((await SELF.fetch("https://other.test/")).status).toBe(404);
    expect((await SELF.fetch("https://guest.test/", { headers: { Upgrade: "websocket" } })).status).toBe(404);
    expect((await SELF.fetch("https://guest.test/robots.txt")).status).toBe(200);
  });

  it("matches IPs and CIDRs", () => {
    expect(ipAllowed("70.40.100.79", ["70.40.100.79"])).toBe(true);
    expect(ipAllowed("70.40.100.80", ["70.40.100.79"])).toBe(false);
    expect(ipAllowed("10.7.39.200", ["10.7.39.0/24"])).toBe(true);
    expect(ipAllowed("10.7.40.1", ["10.7.39.0/24"])).toBe(false);
    expect(ipAllowed("2606:4700::1", ["2606:4700::/32"])).toBe(true);
    expect(ipAllowed("2606:4701::1", ["2606:4700::/32"])).toBe(false);
    expect(ipAllowed("::ffff:70.40.100.79", ["::ffff:0:0/96"])).toBe(true);
    expect(ipAllowed("70.40.100.79", ["2606:4700::/32"])).toBe(false);
    expect(ipAllowed("not-an-ip", ["0.0.0.0/0"])).toBe(false);
    expect(ipAllowed("", [])).toBe(false);
  });

  it("makes readable references", () => {
    for (let i = 0; i < 200; i++) expect(newRef()).toMatch(/^[2-9A-HJKMNP-TV-Z]{4}-[2-9A-HJKMNP-TV-Z]{4}$/);
  });
});
