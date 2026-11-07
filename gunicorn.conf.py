"""gunicorn settings from the environment (see README.md).

BIND_ADDR / PORT        listen address (default 0.0.0.0:8080)
TLS_CERT_FILE / TLS_KEY_FILE  serve HTTPS with this certificate chain and key
"""

import os
import ssl

bind = f"{os.environ.get('BIND_ADDR', '0.0.0.0')}:{os.environ.get('PORT', '8080')}"
# One worker: rate limits and the /events stream are per process. Threads serve
# concurrent guests and SSE subscribers.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "16"))
timeout = 60
graceful_timeout = 20
keepalive = 5
accesslog = None             # the portal writes its own JSON event log
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "warning")
limit_request_line = 6144
limit_request_fields = 60
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

certfile = os.environ.get("TLS_CERT_FILE") or None
keyfile = os.environ.get("TLS_KEY_FILE") or None
if bool(certfile) != bool(keyfile):
    raise SystemExit("TLS_CERT_FILE and TLS_KEY_FILE must be set together")


def ssl_context(conf, default_ssl_context_factory):
    """TLS 1.2+ with ECDHE + AES-GCM only (same suite family as the FIPS SmartZone)."""
    ctx = default_ssl_context_factory()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE+AESGCM")
    ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_CIPHER_SERVER_PREFERENCE
    return ctx
