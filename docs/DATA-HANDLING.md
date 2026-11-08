# Data handling: hosted guest portal (DHA demo)

Scope: the Cloudflare-hosted click-through portal (`cloud/`) and `wispr-connector` on the lab collector, as deployed for
the DHA Round 3 demo lab (2026-11). The lab is not connected to any federal system. This describes what the code does
today. Product changes are noted as such.

## What a guest gives us

Nothing they type. The page asks for no name, email, phone or password, sets **no cookies**, and loads no analytics,
fonts or scripts from anyone else (CSP `default-src 'none'`, same-origin only). What we see comes from the access point's
redirect and from the HTTP request itself.

## What is stored, where, and for how long

| Data | Where | Retention |
|---|---|---|
| Events: redirect params including the guest's `client_mac` and `uip` in clear, the AP `mac`, SSID/WLAN/VLAN, `url`/`StartURL`; the reference; `client_ip_seen` (the lab NAT address); user agent (first 300 chars); NBI result codes, timings and TLS details | Durable Object SQLite (`events`), Cloudflare | 30 days, then deleted by the hub's alarm |
| Visits: ref, CSRF token, validated params, the raw redirect query (≤ 4 KB), state, source IP | Durable Object SQLite (`visits`) | 24 hours |
| Debug exchanges (NBI request/reply bodies, with `RequestPassword`/`UE-Password` masked) | Durable Object SQLite (`debug_exchanges`) | 7 days |
| Connector egress IP, connector status, probe results | Durable Object SQLite (`kv`, `probes`) | Overwritten as they change |
| Durable Object point-in-time recovery (Cloudflare platform) | Cloudflare | Up to 30 days |
| Worker console logs: ref, page, outcome, hub instance, a refused path (≤ 60 chars). No params, MACs or IPs. Invocation (request) logs are **off**. | Workers Logs | Cloudflare's Workers Logs retention for the plan |
| Connector evidence log: one JSON line per NBI call and event, same fields as the events, no passwords | Collector 192.168.37.2 | Rotated daily, kept 30 days |
| Edge security events (if a WAF or other security rule acts on a request), which can include the query string | Cloudflare Security Events | Cloudflare's retention for the plan |

`mac` in the redirect is the access point's MAC, not guest data. `client_mac` and `uip` identify the guest's device on the
guest VLAN. They are kept in clear because the demo's evidence, the R3 golden fixture and RAMPART's checks key on them.
Hashing or truncating them is a product item.

## Never stored

- The SZ NBI password or the guest password. They are Worker secrets, pushed to the connector over the authenticated
  WebSocket, held in memory only, and never written to events, logs or the debug table.
- Tokens. Only their SHA-256 is stored, as Worker secrets.
- NBI request or reply bodies in the event stream (only in the 7-day debug table, with password fields masked).

## Who can read it

- **Holders of the events token** (`wpe_dha_…`): the query API, the SSE stream and the token healthz. Today that is the
  RAMPART collector and John. Tokens are delivered out of band. Rotating one is a `wrangler secret put` of the new token's
  SHA-256. That creates a new Worker version, which resets the Durable Object like a deploy, so it is coordinated the same way.
- **The Cloudflare account owner** (John), through the dashboard and Wrangler.
- The public `/healthz` shows status only: no addresses, MACs, timings or events.
- Guest pages themselves are served only to the lab NAT address (the connector's live egress IP).

## Where it is processed

- Cloudflare Workers and Durable Objects, with **no jurisdiction restriction** (the account default; John, 2026-11-08: a demo
  lab, not connected to any federal system). Durable Objects run in a Cloudflare data centre near where they were first used.
  A product deployment for a real DoD customer would use the `fedramp` jurisdiction and Cloudflare's FedRAMP offering,
  which is a separate decision.
- The connector runs in the lab on the collector and talks only to the SmartZone NBI (192.168.37.6/.8:9443) and to the
  Cloudflare connector host.

## What the connector will do on the cloud's behalf

The cloud can ask the connector for exactly two things: a probe (a Status call for a fixed dummy device) and an accept
(Login/Authorize for one guest). It cannot widen the connector's local ceiling, which is set on the collector:
- allowed NBI hosts and port;
- allowed methods;
- guest CIDRs (the UE-IP must be inside 10.7.39.0/24);
- an NBI calls-per-minute cap.

A compromised cloud account could therefore authorize devices already on the guest VLAN, and nothing else. It is not a
network route into the lab.

## Known limitation: shared anycast before acceptance (R12)

The SZ walled garden allows `guest.lanpulse.com` by name, and the AP resolves it to Cloudflare's **shared** anycast IPs. Those
IPs are then allowed pre-auth for every unauthenticated guest, so other sites that Cloudflare serves from the same IPs are
reachable before a guest accepts the terms (confirmed at M0, 2026-11-08). For the demo this is documented, not fixed. The
fix is a dedicated IP for the portal (Cloudflare Enterprise: static IPs / BYOIP / Address Maps), or hosting the portal
inside the facility network as the VM portal does.

## Product follow-ups (not in the demo)

Hash or truncate guest identifiers at rest; per-tenant encrypted NBI settings entered by the tenant admin; an audit log;
Access-protected admin; configurable retention; FedRAMP jurisdiction option; data-processing documentation per tenant.
