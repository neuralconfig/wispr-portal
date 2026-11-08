import { SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { newRef } from "../src/index";

describe("M0 placeholder", () => {
  it("serves /healthz", async () => {
    const res = await SELF.fetch("https://guest.lanpulse.com/healthz");
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ status: "ok", mode: "placeholder" });
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("echoes redirect params, escaped", async () => {
    const res = await SELF.fetch(
      "https://guest.lanpulse.com/?client_mac=AA:BB:CC:DD:EE:FF&StartURL=https://www.health.mil/&x=%3Cscript%3E",
    );
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("client_mac");
    expect(html).toContain("AA:BB:CC:DD:EE:FF");
    expect(html).toContain("https://www.health.mil/");
    expect(html).not.toContain("<script>");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'none'");
  });

  it("rejects other methods and paths", async () => {
    expect((await SELF.fetch("https://guest.lanpulse.com/", { method: "POST" })).status).toBe(405);
    expect((await SELF.fetch("https://guest.lanpulse.com/nope")).status).toBe(404);
  });

  it("makes readable references", () => {
    for (let i = 0; i < 200; i++) expect(newRef()).toMatch(/^[2-9A-HJKMNP-TV-Z]{4}-[2-9A-HJKMNP-TV-Z]{4}$/);
  });
});
