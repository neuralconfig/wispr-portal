import { SELF } from "cloudflare:test";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { resetAllowCache } from "../src/guest/allow";
import { type DhaBrand, errorPage, infoPage, limits, successPage, termsPage } from "../src/guest/theme-dha";
import { connectFake, E, LAB_IP, settle } from "./helpers";

const B: DhaBrand = {
  organization: "Defense Health Agency",
  facility: "Demo Medical Center",
  network: "Guest Wi-Fi",
  agreeLabel: "Accept",
  dodNotice: true,
  logo: null,
  helpText: "Need help? Please ask at the information desk.",
  idleMinutes: 5,
  sessionMinutes: 60,
  supportFooter: true,
  host: "guest.test",
};
const OFF_HOST = /(?:src|href|url)\s*=?\s*\(?["']?(?:https?:)?\/\//i; // R2: no off-host URLs in markup

describe("DHA theme pages", () => {
  it("terms: one accept button, notice up front, terms in <details>, no scroll box, R7 footer", () => {
    const html = termsPage(B, "75S5-GPMR", "tok", "uip=10.7.39.103&client_mac=02%3AAF");
    expect(html.match(/<button[^>]*id="accept-button"/g)).toHaveLength(1);
    expect(html).toContain(`data-testid="accept"`);
    expect(html).toContain(`<span class="button__label">Accept</span>`);
    expect(html).not.toContain("scrollbox");
    expect(html.indexOf("U.S. Government information system")).toBeLessThan(html.indexOf("accept-button"));
    expect(html).toContain("<summary>Read the full notice and consent</summary>");
    expect(html).toContain("The USG routinely intercepts and monitors communications"); // verbatim notice
    expect(html).toContain("<summary>Read the full terms of use</summary>");
    expect(html).toContain("Sessions end after 5 minutes without use and after 1 hour in total.");
    expect(html).toContain("Your session ends after 5 minutes without use and after 1 hour in total.");
    expect(html).not.toContain("{LIMITS}");
    expect(limits({ ...B, idleMinutes: 30, sessionMinutes: 480 })).toBe("after 30 minutes without use and after 8 hours in total");
    expect(html).toContain("Emergency? Call 911 or tell any staff member.");
    expect(html).toMatch(/Reference <span>75S5-GPMR<\/span> · guest\.test · \d\d:\d\d UTC/);
    expect(html).toContain(`href="/privacy?return=uip%3D10.7.39.103%26client_mac%3D02%253AAF"`);
    expect(html).not.toMatch(OFF_HOST);
    expect(html).not.toMatch(/TRICARE|official website of the United States/i);
  });

  it("terms without the DoD banner: a plain-language monitoring notice", () => {
    const html = termsPage({ ...B, dodNotice: false }, "75S5-GPMR", "tok", null);
    expect(html).toContain("This network is monitored");
    expect(html).not.toContain("The USG routinely intercepts");
    expect(html).toContain(`href="/privacy"`);
  });

  it("logo slot: text wordmark by default, an <img> once a logo is set", () => {
    expect(termsPage(B, "R", "c", null)).toContain(`<p class="hdr__org">Defense Health Agency</p>`);
    expect(termsPage({ ...B, logo: "/static/dha/logo.svg" }, "R", "c", null)).toContain(
      `<img class="hdr__logo" src="/static/dha/logo.svg" alt="Defense Health Agency"`,
    );
  });

  it("success and error keep #ok-title / #err-title; escapes everything", () => {
    const ok = successPage(B, "75S5-GPMR", "https://example.org/?a=1&b=<x>", 10);
    expect(ok).toContain(`id="ok-title"`);
    expect(ok).toContain(`content="10;url=https://example.org/?a=1&#38;b=&#60;x&#62;"`);
    expect(ok).toMatch(/Reference <span>75S5-GPMR<\/span>/);
    const err = errorPage(B, "75S5-GPMR", "Oops <b>", "Body", "/?uip=1");
    expect(err).toContain(`id="err-title"`);
    expect(err).toContain("Oops &#60;b&#62;");
    expect(err).toContain(`href="/?uip=1"`);
    expect(err).toContain(`href="/help?return=uip%3D1"`);
  });

  it("info pages link back to the redirect query on / only", () => {
    expect(infoPage(B, "privacy", "uip=1&x=2")).toContain(`<a href="/?uip=1&#38;x=2">Back to sign-in</a>`);
    expect(infoPage(B, "help", null)).toContain("To sign in, open any web page.");
    expect(infoPage(B, "help", "x".repeat(2001))).not.toContain("Back to sign-in");
    expect(infoPage(B, "accessibility", null)).toContain("WCAG");
    expect(infoPage(B, "help", null)).toContain("Sessions end after 5 minutes without use and after 1 hour in total.");
  });
});

describe("DHA theme through the Worker (PORTAL_THEME=dha)", () => {
  let fake: Awaited<ReturnType<typeof connectFake>> | null = null;
  const get = (path: string) => SELF.fetch(`https://guest.test${path}`, { headers: { "CF-Connecting-IP": LAB_IP } });

  beforeAll(() => {
    E.PORTAL_THEME = "dha";
  });
  afterAll(() => {
    delete E.PORTAL_THEME;
  });
  beforeEach(async () => {
    fake = await connectFake();
    await settle();
    resetAllowCache();
  });
  afterEach(async () => {
    fake?.ws?.close(1000, "test done");
    fake = null;
    await settle();
  });

  it("renders the DHA terms page and serves its assets with a font-src CSP", async () => {
    const res = await get("/?client_mac=02:00:00:00:00:31&uip=10.7.39.31&nbiIP=192.168.37.6&url=http%3A%2F%2Fexample.com%2F");
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Security-Policy")).toContain("font-src 'self'");
    const html = await res.text();
    expect(html).toContain(`href="/static/dha/dha.css"`);
    expect(html).toContain(`<span class="button__label">Accept</span>`);
    for (const p of ["/static/dha/dha.css", "/static/dha/fonts/public-sans-400.woff2", "/static/dha/fonts/public-sans-700.woff2"]) {
      const a = await get(p);
      expect(a.status, p).toBe(200);
      expect(a.headers.get("Cache-Control")).toBe("public, max-age=3600");
    }
    expect((await get("/static/dha/fonts/OFL.txt")).status).toBe(404);
  });

  it("serves Privacy / Accessibility / Help behind the allowlist", async () => {
    const res = await get("/privacy?return=uip%3D10.7.39.31");
    expect(res.status).toBe(200);
    expect(await res.text()).toContain(`<a href="/?uip=10.7.39.31">Back to sign-in</a>`);
    expect((await get("/help")).status).toBe(200);
    expect((await SELF.fetch("https://guest.test/help", { headers: { "CF-Connecting-IP": "198.51.100.1" } })).status).toBe(403);
  });
});

describe("lab theme stays available as the rollback (PORTAL_THEME=lab)", () => {
  let fake: Awaited<ReturnType<typeof connectFake>> | null = null;
  beforeAll(() => {
    E.PORTAL_THEME = "lab";
  });
  afterAll(() => {
    delete E.PORTAL_THEME;
  });
  beforeEach(async () => {
    fake = await connectFake();
    await settle();
    resetAllowCache();
  });
  afterEach(async () => {
    fake?.ws?.close(1000, "test done");
    fake = null;
    await settle();
  });

  it("renders the lab terms page and has no info pages", async () => {
    const get = (path: string) => SELF.fetch(`https://guest.test${path}`, { headers: { "CF-Connecting-IP": LAB_IP } });
    const html = await (await get("/?client_mac=02:00:00:00:00:32&uip=10.7.39.32&nbiIP=192.168.37.6")).text();
    expect(html).toContain(`href="/static/css/customer.css"`);
    expect(html).toContain(`<span class="button__label">I agree, connect me</span>`);
    expect((await get("/privacy")).status).toBe(404);
  });
});
