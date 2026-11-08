// Hosted WISPr portal Worker. Hosts (per wrangler env):
//   GUEST_HOST      guest pages (allowlisted to the connector's egress IP) + public /healthz
//   API_HOST        token-protected API (M-a: healthz; M-b: events stream and query)
//   CONNECTOR_HOST  the connector's WSS endpoint (bearer token; mTLS added by M-d)

import type { Env } from "./env";
import { guestAllowed, hub, TENANT } from "./guest/allow";
import { observe, page, respond } from "./guest/placeholder";
import { bearerMatches } from "./net";
import { VERSION } from "./version";

// The main module may export only handlers and Durable Object classes (workerd rejects others).
export { TenantHub } from "./hub/tenant-hub";

const TEXT = "text/plain; charset=utf-8";
const JSON_TYPE = "application/json";

function json(body: unknown, status = 200): Response {
  return respond(JSON.stringify(body), JSON_TYPE, status);
}

const NOT_ON_GUEST_NETWORK = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Guest Wi-Fi</title></head><body style="font:16px/1.5 system-ui,sans-serif;margin:24px;color:#1B1F24">
<h1 style="font-size:1.25rem">Guest Wi-Fi</h1>
<p>This page is only available on the guest Wi-Fi network.</p></body></html>`;

async function guest(request: Request, env: Env, url: URL): Promise<Response> {
  if (url.pathname === "/healthz") {
    const s = await hub(env).publicStatus(VERSION);
    return respond(s.json, JSON_TYPE, s.httpStatus);
  }
  if (url.pathname === "/robots.txt") return respond("User-agent: *\nDisallow: /\n", TEXT);
  const ip = request.headers.get("CF-Connecting-IP") ?? "";
  if (!(await guestAllowed(env, ip))) {
    console.log(JSON.stringify({ event: "guest_refused", path: url.pathname.slice(0, 60) }));
    return respond(NOT_ON_GUEST_NETWORK, "text/html; charset=utf-8", 403);
  }
  if (url.pathname !== "/") return respond("Not found\n", TEXT, 404);
  const seen = observe(request, env.ENVIRONMENT);
  console.log(JSON.stringify({ event: "m0_visit", ref: seen.ref, params: seen.params.map(([k]) => k) }));
  return respond(page(seen), "text/html; charset=utf-8");
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
  if (url.pathname !== `/v1/tenants/${TENANT}/healthz`) return json({ error: "not found" }, 404);
  if (!(await bearerMatches(request, env.EVENTS_TOKEN_SHA256))) return json({ error: "unauthorized" }, 401);
  const s = await hub(env).tokenStatus(VERSION);
  return respond(s.json, JSON_TYPE, s.httpStatus);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const isUpgrade = request.headers.get("Upgrade")?.toLowerCase() === "websocket";
    if (request.method !== "GET" && request.method !== "HEAD") {
      return respond("Method not allowed\n", TEXT, 405);
    }
    const host = url.hostname.toLowerCase();
    if (host === env.CONNECTOR_HOST) return connector(request, env, url);
    if (isUpgrade) return respond("Not found\n", TEXT, 404);
    if (host === env.GUEST_HOST) return guest(request, env, url);
    if (host === env.API_HOST) return api(request, env, url);
    return respond("Not found\n", TEXT, 404);
  },
} satisfies ExportedHandler<Env>;
