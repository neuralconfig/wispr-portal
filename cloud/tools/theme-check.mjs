// Theme checks (plan: "Client automation contract", R1/R2/R6/R7) against a running local stack:
//   Firefox 500x940 (the RAMPART kiosk) and Chromium 412x915 mobile (Pixel 8).
// For terms, success, error and an info page: screenshots, no off-host requests, no CSP violations or
// script errors, page weight < 150 KB, an axe pass (WCAG 2.1 AA), Public Sans loaded (DHA theme),
// one #accept-button whose bottom is within one scroll (<= 2 viewports) and >= 24 px from the left edge.
// Run through tools/theme_check.py, which starts the stack:  .venv/bin/python tools/theme_check.py
import { readFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { chromium, firefox } from "playwright";

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, "").split("=")));
const { port, host, out, theme = "dha" } = args;
const ORIGIN = `http://${host}:${port}`;
const MAX_BYTES = 150 * 1024;
mkdirSync(out, { recursive: true });

const REDIRECT = new URLSearchParams({
  nbiIP: "127.0.0.1",
  client_mac: "02:AF:A2:20:A0:79",
  mac: "8c:7a:15:3e:b2:40",
  uip: "10.7.39.103",
  url: "http://connectivitycheck.gstatic.com/generate_204",
  StartURL: "https://www.health.mil/",
  ssid: "DHA-Guest",
  wlanName: "DHA-Guest",
  vlan: "739",
  proxy: "0",
});

const DEVICES = [
  { name: "firefox-500x940", type: firefox, ctx: { viewport: { width: 500, height: 940 } },
    launch: { firefoxUserPrefs: { "network.dns.localDomains": host } } },
  { name: "chromium-412x915", type: chromium,
    ctx: { viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36" },
    launch: { args: [`--host-resolver-rules=MAP ${host} 127.0.0.1`] } },
];

// --browsers=chromium runs the kiosk profile in Chromium too (e.g. where Firefox can't start).
if ((args.browsers ?? "firefox,chromium") === "chromium") {
  DEVICES[0] = { ...DEVICES[0], name: "chromium-500x940", type: chromium, launch: DEVICES[1].launch };
}

const failures = [];
const results = [];
function check(ok, what) {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failures.push(what);
}

async function measure(page, label, dev, fn) {
  const offHost = [];
  const errors = [];
  let bytes = 0;
  const onReq = (r) => {
    const u = new URL(r.url());
    if (u.host !== `${host}:${port}` && !u.protocol.startsWith("data")) offHost.push(r.url());
  };
  const onResp = async (r) => {
    try { bytes += (await r.body()).byteLength; } catch { /* redirects, aborted */ }
  };
  const onConsole = (m) => {
    const t = m.text();
    // Local runs are plain http: Chromium ignores COOP there (production is https). Error pages are 4xx by design.
    if (m.type() !== "error" || /Cross-Origin-Opener-Policy header has been ignored/.test(t)) return;
    if (label === "error" && /Failed to load resource: the server responded with a status of 4\d\d/.test(t)) return;
    errors.push(t);
  };
  const onPageError = (e) => errors.push(String(e));
  page.on("request", onReq);
  page.on("response", onResp);
  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  await fn();
  await page.waitForLoadState("networkidle");
  page.off("request", onReq);
  page.off("response", onResp);
  page.off("console", onConsole);
  page.off("pageerror", onPageError);

  const tag = `${dev.name} ${label}`;
  check(offHost.length === 0, `${tag}: no off-host requests ${offHost.join(" ")}`);
  check(errors.length === 0, `${tag}: no CSP violations or script errors ${errors.join(" | ")}`);
  check(bytes < MAX_BYTES, `${tag}: page weight ${(bytes / 1024).toFixed(1)} KB < 150 KB`);
  if (theme === "dha") {
    const font = await page.evaluate(async () => { await document.fonts.ready; return document.fonts.check('700 16px "Public Sans"'); });
    check(font, `${tag}: Public Sans loaded`);
  }
  // meta-refresh: the success page's timed redirect to StartURL (VM parity, redirect_delay_s) is reported, not failed.
  const axe = await page.evaluate(`${AXE}; axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"],
      rules: { "meta-refresh": { enabled: false } } })
    .then(r => r.violations.map(v => v.id + " (" + v.nodes.length + "): " + v.help))`);
  check(axe.length === 0, `${tag}: axe ${axe.join("; ")}`);
  const scrollH = await page.evaluate(() => document.documentElement.scrollHeight);
  const vh = dev.ctx.viewport.height;
  await page.screenshot({ path: `${out}/${theme}-${label}-${dev.name}.png` });
  await page.screenshot({ path: `${out}/${theme}-${label}-${dev.name}-full.png`, fullPage: true });
  results.push({ device: dev.name, page: label, kb: +(bytes / 1024).toFixed(1), scroll_px: scrollH, viewports: +(scrollH / vh).toFixed(2) });
}

for (const dev of DEVICES) {
  const browser = await dev.type.launch(dev.launch);
  const ctx = await browser.newContext(dev.ctx);
  const page = await ctx.newPage();
  const vh = dev.ctx.viewport.height;

  await measure(page, "terms", dev, () => page.goto(`${ORIGIN}/?${REDIRECT}`));
  check((await page.locator("#accept-button").count()) === 1, `${dev.name} terms: one #accept-button`);
  const box = await page.locator('[data-testid="accept"]').boundingBox();
  check(box.y + box.height <= 2 * vh, `${dev.name} terms: Accept within one scroll (bottom ${Math.round(box.y + box.height)} px, viewport ${vh})`);
  check(box.x >= 24, `${dev.name} terms: Accept left gutter ${Math.round(box.x)} px >= 24`);
  results.push({ device: dev.name, page: "terms: accept bottom px", value: Math.round(box.y + box.height) });

  if (theme === "dha") {
    await page.locator("details.more summary").nth(1).click();
    await page.screenshot({ path: `${out}/${theme}-terms-open-${dev.name}-full.png`, fullPage: true });
    await page.goto(`${ORIGIN}/?${REDIRECT}`);
  }

  await measure(page, "success", dev, async () => {
    // Stop the meta refresh from leaving the host: the success page is checked as it renders.
    await page.route((u) => u.hostname === "www.health.mil", (r) => r.abort());
    await Promise.all([page.waitForURL(`${ORIGIN}/accept`), page.click("#accept-button")]);
  });
  check((await page.locator("#ok-title").count()) === 1, `${dev.name} success: #ok-title`);
  const refresh = await page.locator('meta[http-equiv="refresh"]').getAttribute("content");
  console.log(`note ${dev.name} success: timed redirect "${refresh}" (axe meta-refresh, WCAG 2.2.1; VM parity)`);

  await measure(page, "error", dev, () => page.goto(`${ORIGIN}/`));
  check((await page.locator("#err-title").count()) === 1, `${dev.name} error: #err-title`);

  if (theme === "dha") {
    await measure(page, "privacy", dev, () => page.goto(`${ORIGIN}/privacy?return=${encodeURIComponent(REDIRECT.toString())}`));
  }
  await browser.close();
}

console.log(JSON.stringify(results, null, 1));
console.log(failures.length ? `FAIL (${failures.length})` : "PASS");
process.exit(failures.length ? 1 : 0);
