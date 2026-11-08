# Cloudflare setup: hosted guest portal

How the demo deployment is built, and the zone settings around it. The account is John's (Workers Paid). The zone is
`lanpulse.com`, which is a **live site**: deploys create only the portal's own hostnames, and nothing here touches its other
records or settings without John's say-so.

## 1. Workers and hostnames

`cloud/wrangler.jsonc` defines two environments. Each is its own Worker with its own Durable Object namespace, secrets and
custom domains:

| Env | Worker | Custom domains (created by `wrangler deploy`) |
|---|---|---|
| staging | `wispr-portal-staging` | `guest-staging`, `guest-staging-api`, `guest-staging-connector` `.lanpulse.com` |
| production | `wispr-portal-production` | `guest`, `guest-api`, `guest-connector` `.lanpulse.com` |

- Static Assets (`../static`): theme CSS, JS and fonts. With `run_worker_first`, the Worker serves only the files it lists,
  behind the guest allowlist.
- Durable Object class `TenantHub` (SQLite), one object per tenant (`dha`), with jurisdiction **none** (the account default).
- Observability on, **invocation logs off**. Console logs carry refs and outcomes, not params.
- `workers_dev: false`: no `*.workers.dev` URL.

Deploy, from `cloud/`, **after** coordinating with the DHA session and only outside a production freeze:

```
npx vitest run && (cd .. && .venv/bin/python -m pytest -q && .venv/bin/python tools/cloud_e2e.py)
npx wrangler deploy --env staging        # check https://guest-staging.lanpulse.com/healthz, then
npx wrangler deploy --env production
```

A deploy (or a secret change) resets the Durable Object. The connector reconnects within seconds, and SSE clients must
reconnect. Pollers of the query API are unaffected.

## 2. Secrets (per env)

```
npx wrangler secret put CONNECTOR_TOKEN_SHA256 --env <env>   # sha256 hex of wpc_dha_<random>
npx wrangler secret put EVENTS_TOKEN_SHA256    --env <env>   # sha256 hex of wpe_dha_<random>
npx wrangler secret put SZ_NBI_PASSWORD        --env <env>   # the NBI user's password (same as the VM portal's)
npx wrangler secret put SZ_GUEST_PASSWORD      --env <env>   # the guest password for Login (same as the VM's)
```

- Generate a token with `python3 -c "import secrets;print('wpc_dha_'+secrets.token_hex(16))"` and store its SHA-256.
- The tokens themselves live in `~/.config/wispr-portal/<env>-{connector,events}.token` (mode 600) and on the collector,
  never in git.
- Token healthz shows which secrets are set, never their values. The hub refuses Login accepts while `SZ_GUEST_PASSWORD`
  is unset.

Non-secret tenant settings (NBI hosts, port, server name, pin, theme, facility, redirect, rate limits) are in
`cloud/tenants/dha.json`. The per-env Worker var `PORTAL_THEME` overrides `portal.theme` (staging previews `dha`).

## 3. Connector on the collector (192.168.37.2)

The DHA session installs it, with John's OK:

```
sudo deploy/connector/install.sh /path/to/wispr-portal staging|production
```

- The script creates the system user `wispr-connector`, a venv in `/opt/wispr-connector` and the unit `wispr-connector@<env>`.
- Config goes in `/etc/wispr-connector/<env>.env` (see `deploy/connector/connector.env.example`):
  - the dial URL;
  - the token file;
  - IPv4 dialing (so the Worker sees the guests' NAT address);
  - the local policy ceiling: NBI hosts, port, methods, guest CIDRs, rate;
  - the SZ 9443 leaf PEM;
  - local healthz (9180 staging, 9181 production).

## 4. Guest allowlist (instead of a WAF IP rule)

The lab NAT address (70.40.100.79 at M0) is not guaranteed static, so there is no zone WAF IP rule. The Worker admits guest
pages only from the connector's live egress IP (`CF-Connecting-IP` of its WebSocket), plus `egress_cidrs` in the tenant
file. If the NAT changes, the connector reconnects and the allowlist follows. `/healthz` and `/robots.txt` are exempt.

## 5. Zone settings

| Setting | Wanted | Status |
|---|---|---|
| Challenges on guest hosts (Bot Fight Mode, Under Attack, managed/JS challenges, Turnstile) | None (R3) | No challenge seen in M0, g7 or the scripted Firefox (webdriver) runs |
| JavaScript detections | On (zone-wide); the portal's CSP blocks the injected script | Left on (John, 2026-11-08) |
| Rocket Loader, Email Obfuscation, Web Analytics auto-injection, Zaraz | Off on guest hosts (they inject scripts) | Not seen in responses; confirm in the dashboard before the demo |
| Always Use HTTPS | On | Zone setting, John |
| Minimum TLS version | 1.2 | To confirm (John) |
| Edge cipher suites | ECDHE + AES-GCM only (FIPS-aligned) | Optional, needs a custom cipher list on the zone (John) |
| ECH / HTTP/3 | As-is; the walled garden works with them (M0) | Unchanged |
| IPv6 | On (the guest VLAN is IPv4-only, so AAAA answers are harmless) | Unchanged |

Zone-wide changes need John's approval, because `lanpulse.com` serves a live site.

## 6. Planned: mTLS on the connector host

Bearer token today. Planned (needs John: zone changes):
1. Create a Cloudflare-managed client certificate (API Shield → Client Certificates) for the collector.
2. Enable mTLS on `guest(-staging)-connector.lanpulse.com`.
3. Add a WAF custom rule on those hosts that blocks unless `cf.tls_client_auth.cert_verified`.
4. Make the Worker check the presented certificate's SHA-256 for the tenant.
5. Rotation: issue the new cert, overlap both, then revoke the old one.

## 7. Walled garden (SZ side, the DHA session)

- Hotspot portal profile "DHA-Guest-Portal": logon URL `https://guest.lanpulse.com/` (or `guest-staging` for tests).
- The walled garden lists that exact FQDN, with no IP entries.
- The start page stays `https://www.health.mil/`.
- Known limitation: the FQDN resolves to Cloudflare's shared anycast IPs. See R12 in `docs/DATA-HANDLING.md`.
