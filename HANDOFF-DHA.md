# Handoff: wispr-portal → DHA-Wi-Fi (R3 req 7, click-through guest portal)

Written 2026-11-06 by the wispr-portal session. Repo `/Users/john/code/wispr-portal`, branch
`smartzone` (bcce74b code + tests, 2c8c601 docs). Not pushed. No controller calls have been made.

## What it is
An external captive portal for a Hotspot (WISPr) WLAN. The guest selects "I agree" and the
**portal server** calls the SZ WISPr NBI (`POST https://<SZ>:9443/portalintf`). Two modes:
`PORTAL_MODE=customer` (hospital guest page) and `debug` (redirect params, NBI request/reply,
timings, live step log). Details: `README.md`, NBI findings and sources: `SZ-wispr-api.md`.

## Key NBI findings (SZ 7.0.0 WISPr guide; 7.1.x guide not accessible)
- There is no public `Authorize` on SZ. The default is `RequestType: Login` with a fixed `UE-Username`
  (`guest`) against WLAN Authentication Service = **Always Accept**. `SZ_AUTH_METHOD=authorize`
  is an opt-in to test (undocumented; a 304 means unsupported).
- `client_mac` / `uip` (`ENC...`) go back to the NBI verbatim. Decrypt is debug-only.
- `Status` is documented for SZ100/vSZ-E only, so it is off by default on our vSZ-H. Debug mode probes it.
- Every NBI call logs ResponseCode + ReplyMessage + ms + TLS details (JSON lines on stdout).

## SZ settings the portal expects (DHA session applies them, with the user's OK)
1. Administration > External Services > WISPr Northbound Interface: enable, set user + password.
2. Hotspot (WISPr) portal profile: Logon URL External = `https://<portal host>:<port>/`.
   Walled garden: the portal host IP (and DNS name if used). Any MAC format. Keep encrypt-mac-ip on.
3. WLAN: Hotspot (WISPr), that portal profile, Authentication Service = Always Accept.
4. Network: guest VLAN 739 → portal host:port; portal host → 192.168.37.6/.8 TCP 9443.

## Run
```
docker build -t wispr-portal .      # or: docker save wispr-portal | ssh vm docker load
docker run -d --name wp-debug -p 8443:8443 -v $PWD/secrets:/run/secrets:ro \
  -e PORTAL_MODE=debug -e PORTAL_BACKEND=smartzone -e PORT=8443 \
  -e TLS_CERT_FILE=/run/secrets/portal-cert.pem -e TLS_KEY_FILE=/run/secrets/portal-key.pem \
  -e SZ_NBI_HOSTS=192.168.37.6,192.168.37.8 -e SZ_NBI_USERNAME=<user> \
  -e SZ_NBI_PASSWORD_FILE=/run/secrets/sz_nbi_password \
  -e SZ_CA_BUNDLE=/run/secrets/sz-ca.pem -e SZ_TLS_SERVER_NAME=scg.ruckuswireless.com \
  -e SZ_CERT_SHA256=<9443 leaf sha256> -e SECRET_KEY_FILE=/run/secrets/secret_key wispr-portal
```
Files in `secrets/` must be readable by uid 10001. The portal can run over plain HTTP (omit `TLS_*`, use `PORT=8080`) for a first test.

## Open questions for the lab
1. 7.1.1.3 vs the 7.0 guide. 2. Does Authorize exist, and what does it return? 3. Status on vSZ-H.
4. Vendor `ruckus` vs `Ruckus` (a mismatch gives 302). 5. Does Always Accept need a non-empty UE user/password,
and which name shows in the client list? 6. nbiIP = the AP's home node? Does the other node answer?
7. The 9443 certificate and TLS level in FIPS. 8. A real redirect query string. 9. Apple CNA + HTTPS portal.

## Tests so far
64 pytest pass (unit + end-to-end over TLS against `tools/fake_nbi.py`, both modes). Docker
smoke test against the fake NBI OK. Not done: live SZ, axe accessibility run.
