# Connector ↔ hub protocol (version 1)

The connector dials `wss://<connector host>/v1/connect` with `Authorization: Bearer wpc_<tenant>_…`. The Worker checks
the token's SHA-256 against the secret `CONNECTOR_TOKEN_SHA256`. It then hands the socket to the tenant's Durable
Object (`TenantHub`) along with the connection's source IP (`CF-Connecting-IP`).

That source IP becomes the guest allowlist. The connector dials over IPv4 from the same NAT as the guests, so if the
ISP changes the address, the allowlist follows on the next connection. A new connection replaces the old one
(close code 4001).

Every message is one JSON text frame.

| Direction | Message | Meaning |
|---|---|---|
| C → H | `{"type":"hello","protocol":1,"version","env","ceiling":{hosts,port,methods,guest_cidrs,max_nbi_per_min}}` | First frame. The hub closes the socket with code 4002 if it doesn't support `protocol`. |
| H → C | `{"type":"config","config":{backend,hosts,port,path,vendor,api_version,request_username,request_password,auth_method,guest_username,guest_password,status_supported,timeout_s,connect_timeout_s,tls_server_name,cert_sha256,tls_max_version,ca_pem}}` | The NBI configuration, including secrets. The connector keeps it in memory only. |
| H → C | `{"type":"config_unavailable"}` | The hub has no NBI password yet. The connector stays connected and idle. |
| C → H | `{"type":"config_applied",hosts,port,auth_method,server_name,pin,ca_source,ca_sha256,tls_max_version}` | What the connector actually applied (no secrets). The hub records a `connector_connected` event. |
| C → H | `{"type":"config_rejected","error"}` | The config is outside the local ceiling, or the PEM is bad. Recorded as `connector_error`. |
| H → C | `{"type":"rpc","id","op":"probe","args":{"host"}}` | Status for the dummy UE `02:00:00:00:00:00` against that one host. Sent only from the hub's alarm (every `probe_interval_s`). |
| H → C | `{"type":"rpc","id","op":"accept","args":{"ref","params":{client_mac,uip,proxy,nbiIP}}}` | The click-through authorization (`wispr.flow.Authorizer.accept`), one per visit: a double submit joins the running call and a resubmit after success never reaches the connector. |
| C → H | `{"type":"rpc_result","id","ok":true,"result":{…}}` / `{"type":"rpc_result","id","ok":false,"error":"policy"\|"internal","detail"}` | The probe result `{host,reachable,code,message,http_status,duration_ms,tls,error_kind,error}`, or the accept result `{outcome,ok,code,message,total_ms,nbi_calls,nbi_host,tls,events[]}`. |
| C → H | `{"type":"ping"}` (exact bytes) | Every `HEARTBEAT_S` (10 s). The hub's auto-response `{"type":"pong"}` doesn't wake it from hibernation. The connector reconnects if it gets no pong for 3.5 heartbeats. |

**Never forwarded.** The connector refuses anything else:
- any op other than `probe` and `accept`;
- an `accept` whose UE-IP is not a clear address inside `GUEST_CIDRS`;
- any NBI host, port or method outside `ALLOWED_*`;
- more than `MAX_NBI_PER_MIN` operations.

**Probe health.** A node is reachable when it returns a valid NBI reply other than 306 (wrong request password),
400 or 401. Public `/healthz` reports `ok` when the connector is connected (or reconnected within
`reconnect_grace_s`) and at least one node passed a probe in the last 2 minutes.

**Disconnects.** When the socket drops, the hub fails waiting RPCs at once ("connector disconnected"). It never
resends a request through another path, because the controller may already have acted on it.
