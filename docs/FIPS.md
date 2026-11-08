# FIPS and cryptography: hosted guest portal (DHA demo)

Short version: the hop that touches the FIPS SmartZone is restricted to the FIPS-approved TLS 1.2 suites with a pinned
certificate, but **no component of the hosted portal runs a FIPS 140-validated cryptographic module**, and we don't claim
one. The table shows each link.

| Link | Protocol and ciphers | Who terminates | Validated module? |
|---|---|---|---|
| Guest browser → portal (`guest.lanpulse.com`) | HTTPS, terminated at Cloudflare's edge | Cloudflare | Not claimed |
| Connector (collector .2) → Cloudflare (`guest-connector.lanpulse.com`) | WSS over TLS (Python `ssl` default context: TLS 1.2+, system CA store, hostname check) plus a bearer token | Cloudflare edge / connector | No (Ubuntu 24.04 OpenSSL 3.0.13, default provider) |
| Connector → SmartZone NBI (192.168.37.6/.8:9443) | TLS 1.2 with ECDHE + AES-GCM only; certificate pinned | SmartZone (FIPS 140-3 mode, 7.1.1.3) / connector | SZ: yes (vendor claim). Connector: no |
| Inside Cloudflare (Worker ↔ Durable Object) | Cloudflare internal | Cloudflare | Not claimed |
| Data at rest (Durable Object SQLite) | Cloudflare platform encryption at rest | Cloudflare | Not claimed |

## Connector → NBI (the FIPS controller)

Implemented in `wispr/nbi.py` and shared with the VM portal:

- **Cipher list:** `ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256`.
- **Protocol:** TLS 1.2 minimum, and pinned to TLS 1.2 when the tenant sets `tls_max_version`. A FIPS SmartZone only selects
  AES-GCM.
- **Certificate checks:**
  - The SZ's 9443 certificate is the Ruckus factory leaf (CN `scg.ruckuswireless.com`, no SAN) under an unpublished
    Ruckus root.
  - The connector anchors on the leaf itself (partial-chain verification against an operator-supplied PEM), checks the
    name itself (OpenSSL 4 dropped the CN fallback), and checks the SHA-256 pin `bd098ebc…a705`.
  - There is no `verify=False` anywhere.
- **Observed on the lab (2026-11-08 probes):** TLS 1.2, `ECDHE-RSA-AES128-GCM-SHA256`, pin matched, on both nodes. Every NBI
  call records `tls {version, cipher, server_name, cert_sha256}` in its event, so the read-ahead can show it per request.

## What it would take to claim more (product, not demo)

- **Connector:** run it on a base image with a validated module, e.g. an OpenSSL 3 FIPS provider build or a distribution
  FIPS mode (Ubuntu Pro FIPS, RHEL in FIPS mode), with Python linked against it. The cipher policy above already fits
  FIPS-approved suites.
- **Edge:** Cloudflare's FedRAMP offering, and the `fedramp` Durable Object jurisdiction for data at rest. That keeps data in
  FedRAMP data centres. It doesn't by itself make this service FedRAMP-authorized, and it isn't used in the demo (account
  default jurisdiction; John, 2026-11-08).
- **Edge TLS settings** (zone, John applies): minimum TLS 1.2 and edge ciphers limited to ECDHE + AES-GCM on the portal
  hostnames. See `docs/CLOUDFLARE-SETUP.md`.

## Secrets

- The NBI password and guest password are Worker secrets. They are encrypted by Cloudflare at rest and pushed to the
  connector only over the authenticated WSS.
- The connector keeps them in memory only.
- Tokens are stored as SHA-256 hashes.
- Guest-facing CSRF tokens and references come from `crypto.getRandomValues` (Workers runtime CSPRNG).
