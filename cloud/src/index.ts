// Hosted WISPr portal Worker. Hosts (per wrangler env):
//   GUEST_HOST      guest pages (allowlisted to the connector's egress IP) + public /healthz
//   API_HOST        token-protected API: healthz, the events stream (SSE) and the events query
//   CONNECTOR_HOST  the connector's WSS endpoint (bearer token; mTLS added by M-d)

import type { Env } from "./env";
import { guestAllowed, hub, TENANT } from "./guest/allow";
import { parseRedirect } from "./guest/params";
import { respond, securityHeaders } from "./guest/security";
import * as dha from "./guest/theme-dha";
import { type Brand, errorPage, FRIENDLY, successPage, termsPage } from "./guest/theme-lab";
import type { PageResult } from "./hub/tenant-hub";
import tenantConfig from "../tenants/dha.json";
import { bearerMatches } from "./net";
import { VERSION } from "./version";

// The main module may export only handlers and Durable Object classes (workerd rejects others).
export { TenantHub } from "./hub/tenant-hub";

const TEXT = "text/plain; charset=utf-8";
const HTML = "text/html; charset=utf-8";
const JSON_TYPE = "application/json";
const MAX_FORM_BYTES = 16 * 1024;

// Served without events or a ref: browsers and OSes ask for these on their own.
const NOISE = /^\/(?:favicon\.ico|apple-touch-icon[^/]*\.png|\.well-known\/.*)$/;
// Theme assets (Static Assets, directory ../static): only the customer themes' files.
const LAB_ASSETS = ["/static/css/customer.css", "/static/js/customer.js"];
const STATIC = new Set([...LAB_ASSETS, ...dha.DHA_ASSETS, ...(tenantConfig.portal.dha.logo ? [tenantConfig.portal.dha.logo] : [])]);
const INFO_PAGES = new Set<string>(["privacy", "accessibility", "help"]);

/** "lab" (the VM portal's look) or "dha". PORTAL_THEME (per env) wins over the tenant's portal.theme. */
function theme(env: Env): "lab" | "dha" {
  return (env.PORTAL_THEME || tenantConfig.portal.theme) === "dha" ? "dha" : "lab";
}

function json(body: unknown, status = 200): Response {
  return respond(JSON.stringify(body), JSON_TYPE, status);
}

function brand(env: Env): Brand {
  const p = tenantConfig.portal;
  return {
    facility: p.facility,
    helpText: p.help_text,
    welcome: p.welcome,
    agreeLabel: p.agree_label,
    supportFooter: p.support_footer,
    host: env.GUEST_HOST,
  };
}

function dhaBrand(env: Env): dha.DhaBrand {
  const p = tenantConfig.portal;
  return {
    organization: p.dha.organization,
    facility: p.dha.facility,
    network: p.dha.network,
    agreeLabel: p.dha.agree_label,
    dodNotice: p.dha.dod_notice,
    logo: p.dha.logo,
    helpText: p.dha.help_text,
    idleMinutes: p.dha.idle_minutes,
    sessionMinutes: p.dha.session_minutes,
    supportFooter: p.support_footer,
    host: env.GUEST_HOST,
  };
}

/** `back` is the visit's redirect query, for the DHA theme's footer links back to the sign-in page. */
function render(env: Env, r: PageResult, back: string | null = null): Response {
  const headers = { "X-Request-Ref": r.ref };
  if (theme(env) === "dha") {
    const d = dhaBrand(env);
    if (r.page === "terms") return respond(dha.termsPage(d, r.ref, r.csrf ?? "", back), HTML, r.status, headers);
    if (r.page === "success") return respond(dha.successPage(d, r.ref, r.target ?? null, r.delay ?? 0), HTML, r.status, headers);
    const [title, body] = FRIENDLY[r.kind ?? "server_error"] ?? FRIENDLY.server_error;
    return respond(dha.errorPage(d, r.ref, title, body, r.retryUrl ?? null), HTML, r.status, headers);
  }
  const b = brand(env);
  if (r.page === "terms") return respond(termsPage(b, r.ref, r.csrf ?? ""), HTML, r.status, headers);
  if (r.page === "success") return respond(successPage(b, r.ref, r.target ?? null, r.delay ?? 0), HTML, r.status, headers);
  const [title, body] = FRIENDLY[r.kind ?? "server_error"] ?? FRIENDLY.server_error;
  return respond(errorPage(b, r.ref, title, body, r.retryUrl ?? null), HTML, r.status, headers);
}

const NOT_ON_GUEST_NETWORK = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Guest Wi-Fi</title></head><body style="font:16px/1.5 system-ui,sans-serif;margin:24px;color:#1B1F24">
<h1 style="font-size:1.25rem">Guest Wi-Fi</h1>
<p>This page is only available on the guest Wi-Fi network.</p></body></html>`;

async function guest(request: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname;
  if (path === "/healthz") {
    const s = await hub(env).publicStatus(VERSION);
    return respond(s.json, JSON_TYPE, s.httpStatus);
  }
  if (path === "/robots.txt") return respond("User-agent: *\nDisallow: /\n", TEXT);
  const ip = request.headers.get("CF-Connecting-IP") ?? "";
  if (!(await guestAllowed(env, ip))) {
    console.log(JSON.stringify({ event: "guest_refused", path: path.slice(0, 60) }));
    // Inline styles only on this page: the strict CSP would otherwise blank it.
    return new Response(NOT_ON_GUEST_NETWORK, {
      status: 403,
      headers: { ...securityHeaders(), "Content-Type": HTML, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'" },
    });
  }
  if (NOISE.test(path)) return respond("Not found\n", TEXT, 404);
  if (STATIC.has(path) && request.method !== "POST") {
    const asset = await env.ASSETS.fetch(new Request(new URL(path.slice("/static".length), "https://assets.local")));
    if (!asset.ok) return respond("Not found\n", TEXT, 404);
    return new Response(request.method === "HEAD" ? null : asset.body, {
      headers: { "Content-Type": asset.headers.get("Content-Type") ?? "application/octet-stream", ...securityHeaders(true) },
    });
  }
  if (path === "/" && request.method !== "POST") {
    const r = await hub(env).openVisit({
      params: parseRedirect(url.searchParams),
      query: url.search.slice(1),
      userAgent: request.headers.get("User-Agent") ?? "",
      ipSeen: ip,
    });
    console.log(JSON.stringify({ event: "visit", ref: r.ref, page: r.page }));
    return render(env, r, url.search.slice(1));
  }
  if (path === "/accept" && request.method === "POST") {
    let ref = "";
    let csrf = "";
    const len = Number(request.headers.get("Content-Length") ?? "0");
    if (len <= MAX_FORM_BYTES && (request.headers.get("Content-Type") ?? "").startsWith("application/x-www-form-urlencoded")) {
      const raw = await request.arrayBuffer();
      if (raw.byteLength <= MAX_FORM_BYTES) {
        const body = new TextDecoder().decode(raw);
        const form = new URLSearchParams(body);
        ref = (form.get("ref") ?? "").slice(0, 20);
        csrf = (form.get("csrf") ?? "").slice(0, 200);
      }
    }
    const r = await hub(env).accept(ref, csrf, ip);
    console.log(JSON.stringify({ event: "accept", ref: r.ref, page: r.page, kind: r.kind ?? null }));
    return render(env, r);
  }
  if (request.method === "POST") return respond("Method not allowed\n", TEXT, 405);
  // DHA theme: Privacy / Accessibility / Help. Static text, no events; ?return= is the redirect query to go back to.
  if (theme(env) === "dha" && INFO_PAGES.has(path.slice(1))) {
    const back = url.searchParams.get("return");
    return respond(dha.infoPage(dhaBrand(env), path.slice(1) as dha.InfoPage, back), HTML);
  }
  const ref = await hub(env).noteRef("not_found_page", path, ip);
  return render(env, { page: "error", status: 404, ref, kind: "not_found_page" });
}

async function connector(request: Request, env: Env, url: URL): Promise<Response> {
  if (url.pathname !== "/v1/connect") return respond("Not found\n", TEXT, 404);
  if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
    return respond("Expected a WebSocket upgrade\n", TEXT, 426);
  }
  if (!(await bearerMatches(request, env.CONNECTOR_TOKEN_SHA256))) {
    return respond("Unauthorized\n", TEXT, 401);
  }
  const headers = new Headers(request.headers);
  headers.delete("Authorization");
  headers.set("X-Egress-IP", request.headers.get("CF-Connecting-IP") ?? "");
  return hub(env).fetch(new Request("https://hub/connect", { headers }));
}

async function api(request: Request, env: Env, url: URL): Promise<Response> {
  const prefix = `/v1/tenants/${TENANT}/`;
  const route = url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : null;
  if (route !== "healthz" && route !== "events" && route !== "events/stream") return json({ error: "not found" }, 404);
  if (!(await bearerMatches(request, env.EVENTS_TOKEN_SHA256))) return json({ error: "unauthorized" }, 401);
  if (route === "healthz") {
    const s = await hub(env).tokenStatus(VERSION);
    return respond(s.json, JSON_TYPE, s.httpStatus);
  }
  if (route === "events") {
    const q = Object.fromEntries(
      ["since", "until", "ref", "cursor", "limit"].map((k) => [k, url.searchParams.get(k) ?? undefined]),
    );
    const body = await hub(env).queryEvents(q);
    return respond(body, JSON_TYPE, body.startsWith('{"error"') ? 400 : 200);
  }
  const headers = new Headers();
  const last = request.headers.get("Last-Event-ID");
  if (last) headers.set("Last-Event-ID", last);
  const res = await hub(env).fetch(new Request("https://hub/events/stream", { headers }));
  return new Response(res.body, { status: res.status, headers: res.headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const host = url.hostname.toLowerCase();
    const isUpgrade = request.headers.get("Upgrade")?.toLowerCase() === "websocket";
    const postOk = host === env.GUEST_HOST && url.pathname === "/accept" && request.method === "POST";
    if (request.method !== "GET" && request.method !== "HEAD" && !postOk) {
      return respond("Method not allowed\n", TEXT, 405);
    }
    if (host === env.CONNECTOR_HOST) return connector(request, env, url);
    if (isUpgrade) return respond("Not found\n", TEXT, 404);
    if (host === env.GUEST_HOST) return guest(request, env, url);
    if (host === env.API_HOST) return api(request, env, url);
    return respond("Not found\n", TEXT, 404);
  },
} satisfies ExportedHandler<Env>;
