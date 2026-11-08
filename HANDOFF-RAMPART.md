# Hosted portal: handoff to RAMPART (DHA R3 lab)

The click-through guest portal runs on Cloudflare (a Worker plus one Durable Object per tenant) and authorizes guests on
the SmartZone through `wispr-connector` on the collector (192.168.37.2). The VM portal (10.7.39.10:8080) is the fallback.
This file is the contract RAMPART builds against. Lab and SZ changes are made by the DHA session, never from this repo.

## Hosts

| | Production | Staging |
|---|---|---|
| Guest portal (SZ logon URL, walled garden) | `https://guest.lanpulse.com/` | `https://guest-staging.lanpulse.com/` |
| API (events, token healthz) | `https://guest-api.lanpulse.com` | `https://guest-staging-api.lanpulse.com` |
| Connector WSS | `wss://guest-connector.lanpulse.com/v1/connect` | `wss://guest-staging-connector.lanpulse.com/v1/connect` |
| Connector unit on .2 | `wispr-connector@production` (healthz 127.0.0.1:9181) | `wispr-connector@staging` |

- Each environment has its own Worker, Durable Object, tokens and event sequence. Seq numbers are not comparable across them.
- Tokens are delivered out of band and never committed: the events token `wpe_dha_…` and the connector token `wpc_dha_…`.
- **Deploys are coordinated.** The portal session asks the DHA session before every staging or production deploy. A deploy
  resets the Durable Object, which drops the connector socket (it reconnects within seconds) and every SSE stream.
  Production is frozen around rehearsals and the demo.

## Guest pages (R1, R2, R7)

- Exactly one top-level `<button id="accept-button" data-testid="accept">`, in a plain `<form method="post" action="/accept">`.
  There is no iframe, no shadow DOM, no late JS render and no inner scroll box, and the form works without JavaScript.
- The label is theme-dependent: "I agree, connect me" (lab theme) or "Accept" (DHA theme). **Select by id, never by text.**
- Success: `#ok-title`. Error: `#err-title`. Both carry a reference `XXXX-XXXX`.
- R7 support footer on terms and success: `Reference 75S5-GPMR · guest.lanpulse.com · 18:02 UTC`.
- Everything is same-origin on the guest host. There are no third-party requests, and the CSP is `default-src 'none'`
  with `'self'` for scripts, styles, images, fonts, connect and form-action.
- DHA theme only: `/privacy`, `/accessibility` and `/help` on the same host. They are static and emit no events.
- Guest pages are served only to the connector's live egress IP (the lab NAT) plus the tenant's static CIDRs. Anyone else
  gets a 403 "only available on the guest Wi-Fi network". `/healthz` is public.
- Rate limits: page views 300/min per source IP; accepts 10/min per `client_mac` (429 + `rate_limited` event).
- Themes: the tenant setting `portal.theme` (`lab` | `dha`), overridden per environment by the Worker var `PORTAL_THEME`.
  As of 2026-11-08 staging previews `dha` and production runs `lab`.

## Events: the query API is the source of truth

Decision (John, 2026-11-08): RAMPART polls the query API every 1 s by cursor. SSE is only an early hint, and both feed one
dedupe by `seq`. Durable Object resets (deploys, Cloudflare runtime restarts) can leave an SSE connection open and silent.
Events are written to SQLite with their seq **before** they are pushed, so the query API never misses one.

```
GET /v1/tenants/dha/events?cursor=<seq>&limit=1000
Authorization: Bearer wpe_dha_…
→ 200 {"events":[{seq, ts, event, ref?, …lab fields}], "next_cursor":"<seq>"|null, "head_seq":<int>}
```

- Params, all optional and ANDed together:
  - `cursor`: seq > cursor.
  - `ref=XXXX-XXXX`
  - `since` / `until`: ISO 8601, matched on the hub's **insert** time, not the JSON `ts`. Events relayed from the
    connector carry the connector's own `ts`, a few hundred ms earlier.
  - `limit`: default 100, maximum 1000.
- Always in ascending seq order.
- `next_cursor` is non-null only when more than `limit` rows match: fetch again at once with it. `null` means "all there is right
  now", not end of stream.
- `head_seq` is the current maximum seq, read in the same synchronous step as the page. A poller can start at `cursor=head_seq`.
- Errors:
  - 400 `{"error": …}`: bad cursor, ref, or time.
  - 401: no token or a wrong token.
  - 5xx or a timeout: retry on the next tick and keep the cursor.
- Retention: 30 days.

Polling loop:

```
cursor = head_seq (or the first call uses since=<run start − 5 s>)
every 1 s:
    page = GET ?cursor=cursor&limit=1000
    for e in page.events: handle(e) unless seen(e.seq)
    cursor = max(cursor, last e.seq, page.head_seq if page.next_cursor is null)
    if page.next_cursor: repeat immediately
```

### SSE (optional, early delivery)

`GET /v1/tenants/dha/events/stream` (same token).
- The first frame is data-less: `: instance=<8 hex> booted_at=<ISO>` (a comment), then `retry: 3000` and `id: <current seq>`.
- Then `id: <seq>` + `data: <event JSON>` for each event, and `: keep-alive` every 15 s.
- Without `Last-Event-ID` the stream is live only. With it, the stream replays from that seq and then goes live.
- The hub ends streams after 15 min, and as soon as it notices that it is a stale instance. Treat 35 s without any bytes
  (comments included) as dead and reconnect with `Last-Event-ID`.

### Event names

Guest flow (lab parity, the same keys as the R3 golden fixture):
- Page and session: `redirect_received`, `terms_shown`, `accept_clicked`, `success_shown`, `error_shown`, `rate_limited`.
- Relayed from the connector: `nbi_request`, `nbi_response`, `auth_result`.

The hosted portal adds:
- the fields `seq`, `client_ip_seen`, `via`, `connector_ms` and `overhead_ms`, plus `client_mac`/`uip` on session events;
- `connector_connected`, `connector_disconnected` and `connector_error`;
- `hub_started` `{instance, previous_instance, streams_lost, streams_open_since}`. This is emitted only when a new instance
  finds that a previous instance had SSE streams open, i.e. it was reset or replaced underneath them. Instances are also
  rebuilt on every hibernation wake (about twice a minute), and those boots are quiet: only a `hub_boot` line in Workers Logs.

`auth_result.total_ms` is the NBI time measured on the connector. `overhead_ms` is the hub ↔ connector round trip
(~36 ms). Use these for R11 timing, not the event's arrival time.

## Health

- Public `GET https://guest.lanpulse.com/healthz`:
  - fields: `status` ok|down, `version`, `mode`, `backend`, `nbi_hosts`, `connector.connected`,
    `nbi[{node, reachable, checked_at}]`;
  - 200 when the connector is connected and at least one node passed a probe in the last 2 minutes, otherwise 503
    (after a 20 s reconnect grace).
- Token `GET /v1/tenants/dha/healthz` adds:
  - per-node codes, ms and TLS;
  - the connector's applied config, version and egress IP;
  - which secrets are set (never their values);
  - `hub {instance, booted_at, head_seq, streams_open}`;
  - the last 20 events.
- Connector local healthz on .2: `http://127.0.0.1:9181/healthz` (production) gives `wss_connected`,
  `config_applied` and `last_probe`.
- Probes run from the hub's alarm every 30 s: a Status for the dummy UE `02:00:00:00:00:00` against each node.

## Measured (2026-11-08)

- g7 on production (run 1092, Guest A + the Pixel captive sheet): NBI 201, `total_ms` 309/341 (VM baseline 240–310),
  `overhead_ms` ~36.
- Rehearsal g1–g9 on production was running from 22:12Z; results are in the DHA session.

## Known limitations (for the read-ahead)

- **R12, shared anycast:** the walled-garden FQDN resolves to Cloudflare's shared anycast IPs, and the AP allows those IPs
  pre-auth. So other Cloudflare-hosted sites on the same IPs are reachable before acceptance. The fix is dedicated IPs
  (Enterprise). See `docs/DATA-HANDLING.md`.
- The guest allowlist follows the connector's egress IP. If the lab NAT IP changes, guests are refused until the connector
  reconnects (within seconds; it reconnects on any socket loss).
- Connector authentication is a bearer token; mTLS on the connector host is planned and needs zone changes.

## Fallback to the VM portal (DHA session; John's go/no-go)

1. SZ Hotspot profile "DHA-Guest-Portal": logon URL back to `http://10.7.39.10:8080/`. Walled garden: add `10.7.39.10`,
   then remove the lanpulse FQDN.
2. Re-add 10.7.39.10 to guest isolation / L3 ACP and the MikroTik allow rule, both of which were removed at the M10 cutover.
3. RAMPART: `portal.health` back to the VM's `/healthz`; the event source back to the VM's JSONL reader.
4. Check: Guest A accept → `auth_result` 201 in the VM's events.

The VM uses the same NBI user and password, so no SZ credential change is needed in either direction.
