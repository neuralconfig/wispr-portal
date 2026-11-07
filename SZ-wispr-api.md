# SmartZone WISPr Northbound Interface (NBI): what the portal relies on

The portal server authorizes a guest by calling the SmartZone WISPr NBI itself. The guest's
browser never talks to the controller. This file records what the docs say, where they
say it, and what is still open. Nothing here was tested on a live controller yet: the DHA
lab test (SZ 7.1.1.3 FIPS, vSZ-H, 2 nodes) comes next.

## Sources

| Id | Document | Notes |
|----|----------|-------|
| **G70** | *RUCKUS SmartZone (ST-GA) Hotspot WISPr Interface Reference Guide, 7.0.0*, part 800-73386-001 Rev A, Feb 2024 (SZ100/vSZ-E, SZ300/vSZ-H) | Main reference. Page numbers below are the guide's printed page numbers. |
| **G710** | *RUCKUS SmartZone (LT-GA) Hotspot WISPr Interface Reference Guide, 7.1.0*, RevA 12102024 (support.ruckuswireless.com document 4949) | **Not read.** The PDF needs a support login and the linked HTML version returns 404. No 7.1.x WISPr guide was available, so every 7.0 statement below needs checking against 7.1.1.3. |
| **FIPS** | *RUCKUS FIPS and Common Criteria Configuration Guide for SmartZone and AP, 7.1.1.3*, 800-73721-001 Rev A, Dec 2025 | p.63: the WISPr NBI is one of the "secured communication services available in FIPS". p.153-154: Guest Access, Web-Auth and Open-None WLANs are disabled in FIPS. p.47-50: HTTPS client/server security levels. p.83: Hotspot (WISPr) certificate mapping. |
| **R1** | *RUCKUS One Hotspot WISPr API Reference*, 800-73417-001 Rev B (summarised in `R1-wispr-api.md`) | Used for comparison only. Not proof of SZ behaviour. |
| **CF-NBI** | RUCKUS Confluence (internal), "Northbound Portal Interface Commands", based on the **SZ 5.1 GA** codebase | Internal engineering page, not customer documentation. |
| **CF-R1AA** | RUCKUS Confluence (internal), "ACX Always Accept support in WISPr Authentication HLD" | R1 (cloud) design for click-through `Authorize`. |
| **CF-FLOW** | RUCKUS Confluence (internal), "WISPr-Open-Auth-Succ :: Code Flow of NBI" (SZ 5.1 logs) | Shows a real NBI Login exchange. |

> The CF-* pages are RUCKUS-internal. This file only cites them by title. Check with
> RUCKUS before you share this file outside the RUCKUS/DHA project.

## 1. Endpoint, transport and authentication

- `POST https://{controller}:9443/portalintf`. HTTP is also on 9080 (G70 p.35, Table 9). The URI is fixed. The NBI listens on the management, control and user-defined interfaces (G70 p.35, p.59).
- Requests must be JSON over **POST**: "The controller will not accept a request with the GET request command" (G70 p.36).
- Every request carries `RequestPassword` (and, in the documented examples, `RequestUserName`). Both are set under *Administration > External Services > WISPr Northbound Interface* (G70 p.36; FIPS p.63: "Enter the User Name and Password"). On SZ300/vSZ-H the user name exists for MSP partner users (G70 p.61).
- The redirect gives the portal `nbiIP`, described as "the IPv4 of controller's Northbound Interface" (G70 p.53). **Portal rule:** `nbiIP` is used only if it is in `SZ_NBI_HOSTS`. Any other value is refused and logged as `nbi_not_allowed`, so a forged redirect cannot make the server call an arbitrary host (no SSRF).
- **Portal:** uses HTTPS 9443 only. HTTP 9080 is not offered.

## 2. Click-through: `Authorize` or `Login`?

**Answer: the public SmartZone documentation has no click-through `Authorize` command.**
G70 p.37 lists the UserOnlineControl commands as **Login, Login Async, Logout, Status,
Disconnect, Enrichment Info**. GetConfig adds **Encrypt** and **Decrypt** (G70 p.43). The FIPS
guide adds nothing about NBI commands.

- RUCKUS One has `Authorize` for click-through ("Always Accept"; CF-R1AA). The existing R1 mode of this portal uses it. The R1 public reference documents only `Login` (R1 doc, "JSON Commands"). **No R1 parity is assumed for SZ.**
- The internal CF-NBI page (SZ **5.1** code) lists `RequestType` values `LOGIN`, `LOGIN_ASYNC`, `STATUS`, `LOGOUT`, `DISCONNECT`, **`AUTHORIZE` ("Authorized directly")**, plus `Encrypt`/`Decrypt`. So the SZ NBI has had an undocumented Authorize command. **Lab (run 1b, 2026-11-06): it exists on 7.1.1.3 FIPS vSZ-H.** `Authorize` returned `201 Login succeeded` in 187 ms, and Status went 100 → 101. The SZ sent **no RADIUS request at all** (radius1 log and radius2 pcap), so Authorize bypasses the WLAN's authentication service. It is still undocumented, so RUCKUS should confirm it is supported before production relies on it.

**What the portal does:**

| Setting | Request | When to use |
|---|---|---|
| `SZ_AUTH_METHOD=login` (**default**) | `RequestType: Login` with a fixed `UE-Username` / `UE-Password` from config (`SZ_GUEST_USERNAME`, default `guest`) | Documented path (G70 p.38). G70 p.33 Table 8 lists "Local DB, Always Accept, and any AAA servers" as the options, and with Always Accept any user name and password works. **On FIPS 7.1.1.3, Always Accept and Local DB need proxy (through-controller) auth**, so without proxy the lab uses a real shared RADIUS account (`dha-guest`, PAP). Proven in the lab, runs 1 and 1b. |
| `SZ_AUTH_METHOD=authorize` (opt-in) | `RequestType: Authorize`, no UE credentials | Undocumented on SZ (CF-NBI), but **proven on FIPS 7.1.1.3 (run 1b): 201, and no RADIUS**. It is real credential-less click-through: no guest account and no guest RADIUS server are needed at authorization time. The WLAN still has to name some authentication service to be created. Get RUCKUS support confirmation before relying on it. |
| `SZ_AUTH_METHOD=login_async` (opt-in) | `LoginAsync`, then poll `Status` | Needs `Status` support (see §4). Polls every `SZ_ASYNC_POLL_INTERVAL` s for up to `SZ_ASYNC_MAX_WAIT` s. |

Login request as built by the portal (G70 p.38 example and field names):

```json
{
  "Vendor": "ruckus",
  "RequestUserName": "<SZ_NBI_USERNAME>",
  "RequestPassword": "<SZ_NBI_PASSWORD>",
  "APIVersion": "1.0",
  "RequestCategory": "UserOnlineControl",
  "RequestType": "Login",
  "UE-IP": "<uip from the redirect, verbatim>",
  "UE-MAC": "<client_mac from the redirect, verbatim>",
  "UE-Proxy": "<proxy from the redirect, default 0>",
  "UE-Username": "<SZ_GUEST_USERNAME>",
  "UE-Password": "<SZ_GUEST_PASSWORD (random per start if unset)>"
}
```

Sync Login replies (G70 p.38-39, Table 11): **201** Login succeeded, **101** Client authorized
(already authorized: the portal treats it as success, so a double click or reload is
harmless), **300** Not found, **301** Login failed, **400** Internal server error, **401**
Authentication server error, **302-306** general errors. "If an authentication process has a
result (not pending), the controller responds to it only once": a repeat query after a 201
returns 101, and after a 301 returns 100 (G70 p.39 note).

`Vendor`: the SZ guide examples send `"ruckus"` and the replies say `"Ruckus"`. CF-NBI says
the value is checked against a controller setting and a mismatch gives **302**. The default is
`ruckus` (configurable as `SZ_VENDOR`). Lab: `ruckus` is accepted on 7.1.1.3.

## 3. Encrypted UE-MAC / UE-IP (`ENC...`)

- **FIPS overrides this (lab, 2026-11-06):** on 7.1.1.3 with FIPS compliance on, MAC/IP encryption is **disabled**. The SZ CLI says "The feature is disabled by enabling FIPS compliance" (seen by the user; a question to RUCKUS engineering is open). The redirect therefore carries `client_mac` and `uip` **in clear**, as seen in run 1. The portal handles clear and ENC values the same way.
  - Consequences: the clear MAC/IP sit in the guest's URL and browser history and in the portal's server log. Customer-mode pages and SSE still mask them.
  - A guest could also edit `client_mac`/`uip` in the URL to name another device. The impact is limited: customer mode only sends Login, and this is click-through anyway. Logout, Disconnect and Status are debug-only. A possible hardening step, not yet implemented: require `uip` to equal the request's source IP when the portal is on the guest VLAN without NAT, as in the lab.
- The controller encrypts `client_mac` and `uip` in the redirect by default (G70 p.43: "By default the encryption is enabled"). Turn it off with the CLI `no encrypt-mac-ip` and check it with `show running-config encrypt-mac-ip` (G70 p.43-44).
- "Northbound Interface (NBI) expects to receive encrypted UE-IP and UE-MAC address (For example, ENC12bc...) when the request category is UserOnlineControl" (G70 p.37 note). The NBI decrypts them itself and returns them re-encrypted in the reply (G70 p.37, p.53).
- **Portal rule:** `client_mac` and `uip` go back to the NBI **exactly as received**: no decrypting, re-casing or reformatting. Clear (unencrypted) values are also passed through unchanged in the format the portal profile uses ("Redirected MAC Format", G70 p.27). CF-NBI says plain values are accepted "for backward-compatible". R1 says an unencrypted UE-MAC "must exactly match the client_mac in the query string".
- To see clear values, use `GetConfig` / `Decrypt` with `"Data": "<ENC...>"` → `ResponseCode 200`, `"Data": "<clear>"` (G70 p.43-47). The legacy `EncryptIP`/`DecryptIP` are deprecated since 6.0 (G70 p.43). The portal calls Decrypt only in **debug** mode (the *Decrypt MAC/IP* button) or when `LOG_DECRYPT_UE=true`, which writes the clear MAC to the server log only.
- The `ENC` values are not secrets in themselves, but they identify the client. Customer-mode output (pages and SSE) masks them as `ENC1234…abcd`. The server log keeps the full value.
- The portal accepts `ENC` followed by 8-256 hex digits, or a MAC in `aa:bb:..`, `aa-bb-..`, `aabb..` or `aabb.ccdd.eeff` form. Anything else is rejected before any NBI call.

## 4. Status, Logout, Disconnect

- **Status** (G70 p.39, Table 12): replies 201/202 while an authentication is pending, otherwise **100** (unauthorized) or **101** (authorized). **G70 says: "This topic is only applicable to SZ100 and vSZ-E platforms."** The DHA cluster is **vSZ-H**, so `SZ_STATUS_SUPPORTED` defaults to `false` and customer mode never depends on Status. Debug mode still sends Status before and after the authorization (`DEBUG_STATUS_CHECKS`) and shows the reply. A 304 there is recorded, not treated as a failure.
- **Logout** (G70 p.41): changes the UE from authorized to unauthorized. TCP sessions stay up and the UE stays associated. The guide gives no reply table. The portal treats 200 OK as done.
- **Disconnect** (G70 p.41, Table 14): unauthorizes and disassociates the UE. Replies 200 OK, or 100 if already unauthorized.
- Logout and Disconnect are debug-mode buttons only. Customer mode has no logout.

## 5. Reply codes (G70 p.44, Table 15)

| Code | Meaning | Used in | Portal outcome (customer message) |
|---|---|---|---|
| 100 | Client unauthorized | Status, Logout/Disconnect | `login_failed` (after a failed async login) |
| 101 | Client authorized | Login, Status | **success** |
| 102 | Enrichment Info | EnrichmentInfo | n/a |
| 200 | OK | Logout/Disconnect, GetConfig | success for Decrypt/Logout; also success for `Authorize` |
| 201 | Login succeeded | Login, Status | **success** |
| 202 | Authentication pending | LoginAsync, Status | poll Status (async only) |
| 300 | Not found | all UOC | `not_found` ("We could not find your device...") |
| 301 | Login failed | Login, Status | `login_failed` |
| 302-306 | Bad request / Version / Command / Category not supported / Wrong request password | all | `portal_config` ("temporarily unavailable") |
| 400, 401 | Internal server error / Authentication server error | all / Login, Status | `controller` ("temporarily unavailable") |

Every NBI call is logged as `nbi_request` and then `nbi_response` with `ResponseCode`,
`ReplyMessage`, `http_status`, `duration_ms`, TLS version, cipher and certificate SHA-256, or
as `nbi_error` (`connect`, `tls`, `timeout`, `http`, `bad_reply`). That happens in both modes.
`ResponseCode` may come back as a string (CF-NBI example `"201"`), so the portal converts it
to an integer.

## 6. TLS to the NBI (FIPS)

- FIPS guide p.47-50: on a FIPS controller the HTTPS **server** security level is 1 or 2. Level 2 allows only `TLS_ECDHE_{RSA,ECDSA}_WITH_AES_{128,256}_GCM_SHA{256,384}` and the TLS 1.3 `TLS_AES_{128,256}_GCM_*` suites. Level 1 also allows CBC suites. The guide does not say whether port 9443 follows that setting (**open**).
- **Portal client:** TLS 1.2 minimum. The TLS 1.2 cipher list is `ECDHE-{ECDSA,RSA}-AES{256,128}-GCM-SHA{384,256}` only. The certificate chain is **always verified** (`CERT_REQUIRED`, hostname check). There is no `verify=False` anywhere. The CA comes from `SZ_CA_BUNDLE` (else the system store). The name verified is `SZ_TLS_SERVER_NAME` if set, else the NBI host, and `SZ_CERT_SHA256` can pin the leaf certificate. Python cannot narrow the TLS 1.3 suites. OpenSSL also offers ChaCha20 there, but a FIPS server only picks AES-GCM. Set `SZ_TLS_MAX_VERSION=1.2` for a strict AES-GCM-only offer.
- The factory certificate is CN `scg.ruckuswireless.com`, issued by "Ruckus Certificate Authority" (lab observation on the management UI; G70 p.53 `sip` describes the same default). When the portal connects by IP, that name will not match. Either import a lab-CA certificate for the NBI host's IP/DNS name and map it to the service, or set `SZ_TLS_SERVER_NAME=scg.ruckuswireless.com`, give the Ruckus CA as `SZ_CA_BUNDLE`, and pin `SZ_CERT_SHA256`. The factory key may be shared across units, so the pin matters with the factory certificate.
- Which certificate 9443 actually presents (management-web cert vs Hotspot (WISPr) mapping, FIPS p.83) is **open**.

## 7. Redirect parameters (G70 p.53-54, Table 16)

`client_mac` (encrypted UE MAC), `uip` (encrypted UE IP), `nbiIP` / `nbiIPv6`, `mac` (AP MAC),
`apip`, `ssid`, `wlanName`, `url` (original URL), `startUrl` (portal-profile start page),
`reason` (`Un-Auth-Captive` / `Un-Auth-SSL-Captive`), `proxy`, `vlan`, `wlan`, `sip`, `dn`,
`lid`, `loc`, `sshTunnelStatus`, `zoneId`, `zoneName`. **FIPS 7.1.1.3 spells the start page `StartURL`** (lab, 2026-11-06), so the portal matches parameter names case-insensitively. The spelling received is logged as `aliases` in `redirect_received`, and sending both spellings is rejected as a repeated parameter. All are validated (see
`wispr/params.py`). Only `client_mac` is required. Unknown parameters are shown in debug mode
and never used. After success the portal sends the guest to `startUrl`, else `url`, else
`DEFAULT_REDIRECT_URL`. Only http(s) URLs are allowed.

## 8. Other notes from the docs

- Apple CNA "only works for HTTP redirect. It does not work if the external portal is in HTTPS" and "does not support IPv6 addresses" (G70 p.53). This matters for iPhones if the portal is HTTPS-only. The DHA test clients are Android (Pixel 8) and a WLAN Pi with Chromium.
- "If Traffic Class Profile or Use Token Redirect URL is enabled, Smart Client Support is set to None" (G70 p.31).
- The AP can redirect to a secondary portal when it cannot reach the controller, but "No NBI is supported for backup" (G70 p.26). WISPr survivability uses the ZD-style AP API, which this portal does not implement.
- Session timeout and grace period come from the Hotspot portal profile (G70 p.27), not from the NBI.

## Lab results: FIPS vSZ-H 7.1.1.3.571, run 1 (2026-11-06)

Run by the DHA-Wi-Fi session: WLAN Pi client, curl in netns `guest`, portal in debug mode on
`dha-portal` 10.7.39.10:8080, SZ_AUTH_METHOD=login. Portal refs 49JV-C6TP (failed) and
482Y-V4N8 (passed). Raw evidence (events.jsonl, accept JSON, RADIUS logs) is kept by the DHA-Wi-Fi
project under `evidence/r3-guest/20261106/portal-run1/`.

- **Always Accept is not offered without proxy (new finding).** On this FIPS cluster, Always
  Accept and Local Database exist only when authentication goes through the controller (proxy),
  confirmed in the SZ UI. The non-proxy services are zone RADIUS servers only. The lab therefore
  uses a **real shared credential**: `SZ_GUEST_USERNAME=dha-guest` plus
  `SZ_GUEST_PASSWORD_FILE`, checked by PAP on a separate guest-only FreeRADIUS virtual
  server (UDP 1912/1913, one account, EAP refused). The SZ client list shows `dha-guest` for every guest.
- **The SZ sends the RADIUS Access-Request itself**, from the SZ node (192.168.37.6), not from the
  AP, even with `throughController=false`. The RADIUS server must list the SZ nodes as clients.
  Before that was fixed, the SZ never answered the Login and the portal hit its 12 s
  `SZ_NBI_TIMEOUT` (ref 49JV-C6TP: `nbi_error` timeout, then Status still 100). Set `SZ_NBI_TIMEOUT` above the
  SZ's RADIUS timeout × retries + failover, or a slow primary RADIUS shows the guest an error
  while the SZ may still authorize the client. The SZ included Message-Authenticator.
- **Login works:** `201 Login succeeded` in 301.6 ms; /api/accept took 565 ms end to end.
- **Status works on vSZ-H 7.1.1.3** (unlike what G70 p.39 implies): 100 "Client unauthorized" before and 101
  "Client authorized" after. The reply carries the AP MAC, SSID, `wsgWlanId` 9, the zone id and UE-Username.
- **Vendor:** the portal sends `ruckus` and the SZ accepts it. Replies carry `"Vendor": "Ruckus"`.
- **nbiIP** was 192.168.37.6, the node that answered. The other node was not tested.
- **9443 TLS in FIPS:** TLS 1.2 `ECDHE-RSA-AES128-GCM-SHA256`, factory leaf
  CN=scg.ruckuswireless.com (SHA-256 bd098ebc...a8a705). Leaf-as-anchor plus pin works.
- **Real redirect** (302 from the AP, `Server: GoAhead-Webs`), with its parameters in this order:
  `nbiIP, client_mac, domain_name, reason, wlanName, dn, ssid, mac, url, proxy, vlan, wlan, sip,
  zoneName, apip, sshTunnelStatus, uip`.
  - `client_mac` and `uip` arrived **in clear**, not ENC. FIPS compliance disables Encrypt MAC/IP
    (section 3).
  - MAC format `AA:BB:CC:DD:EE:FF`.
  - `dn` and `sip` = `scg.ruckuswireless.com`.
  - `domain_name=Administration Domain` (not in G70 Table 16).
  - `zoneName` is not the zone name but an opaque `<22-char token>_<epoch ms>`, where the epoch is
    the redirect time.
  - No `startUrl`, so the portal used `url`.
- **Walled garden:** before authorization only the portal and DNS were reachable. After it,
  traffic was open (lab gateway, no segmentation yet).

## Lab results: run 1b (2026-11-06, 22:22-22:33 UTC)

Client: Pi `guest` netns, firefox-esr (streamed over VNC). Portal in debug mode. Refs CMPA-ZAF7
(login, logout), AGVJ-W7V9 (authorize, disconnect), ACH6-MX6C (back to login).

| Request | Reply | NBI time | Effect |
|---|---|---|---|
| Login | 201 Login succeeded | 255 / 292 ms | Status 100 → 101. UE-Username `dha-guest` |
| Logout | 200 OK | 227 ms | Client captive again at once. Status 100 |
| Authorize | 201 Login succeeded | 187 ms | Status 100 → 101. **No RADIUS packet** |
| Disconnect | 200 OK | 175 ms | AP deauthenticates the client (wlan1 down ~3 s, rejoins by itself). Status 100 |
| Status | 100 / 101 | 66-124 ms | |

- **RADIUS from a Login:** the UDP source is the SZ node (192.168.37.6), but NAS-IP-Address = the AP
  (192.168.37.99) and NAS-Identifier = the AP BSSID. Proxy-State is present, and Message-Authenticator is
  used both ways. The SZ proxies the AP's RADIUS for NBI logins even with a non-proxy WLAN
  auth service, so the RADIUS server must accept the SZ nodes as clients.
- The Authorize reply has no UE-Username.
- **Fresh-MAC Authorize** (random MAC, ref GGT7-EC9C): Status 100 → Authorize 201 (190 ms) → Status 101 with UE-Username = the MAC (`025b5d617954`). The SZ client list shows that user name, auth "HotSpot(Wispr)+Open", AUTHORIZED, VLAN 739. No RADIUS packets.

## Open questions (lab or RUCKUS)

1. *(Partly answered by run 1: Login and Status behave as in G70.)* Does **7.1.1.3 FIPS** still match the 7.0.0 guide? The 7.1.0 guide (G710) could not be downloaded without a support login.
2. **Answered (run 1b):** `Authorize` exists on 7.1.1.3 FIPS. It returns 201 "Login succeeded" and sends no RADIUS. For a fresh client the SZ records the **client MAC as the user name** (lowercase, no separators, e.g. `025b5d617954`; auth "HotSpot(Wispr)+Open"). The `dha-guest` seen after Authorize in run 1b was left over from the earlier Login on that MAC (fresh-MAC check, page GGT7-EC9C, 22:49 UTC, 0 RADIUS packets). Still open: RUCKUS support status.
3. ~~Status on vSZ-H~~ **Answered:** it works (run 1).
4. **Answered for the default:** `ruckus` is accepted, and replies say `Ruckus`. Whether it is configurable is still open.
5. **Moot on FIPS 7.1.1.3 non-proxy:** Always Accept is not offered, so a real shared credential is used, and the client list shows `dha-guest`. Still open for proxy mode: with Always Accept, does the NBI still require non-empty `UE-Username` / `UE-Password`, and what user name shows in the SZ client list and accounting?
6. *(Partly answered: nbiIP = .6 answered.)* In a 2-node cluster, does `nbiIP` point to the node the AP is homed on? Does the other node also answer for that UE (is client state cluster-wide)? The portal only fails over on connection errors, never after a request was sent.
7. **Answered:** the factory leaf (CN=scg.ruckuswireless.com, no SAN, no chain) with TLS 1.2 ECDHE-RSA-AES128-GCM-SHA256. Whether an uploaded cert replaces it on 9443 is still open.
8. **Answered** (see Lab results). Encrypt MAC/IP is disabled by FIPS compliance (section 3), so clear values are expected. Open: RUCKUS confirmation, and whether `zoneName` can be decoded.
9. NBI behaviour on a request for a UE that is not on a Hotspot WLAN (expected 300), and on a Login for a UE in grace period.
10. **Answered:** how long the SZ waits on RADIUS. WLAN 9 `radiusOptions`: nasRequestTimeoutSec 3, nasMaxRetry 2, nasReconnectPrimaryMin 5. Observed: 5 Access-Requests 3 s apart (~15 s) to a dead primary, then the SZ moves to the secondary and retries the primary after 5 min. So the first guest after the primary fails needs more than 15 s. The SZ default for `SZ_NBI_TIMEOUT` is now 20 s.
