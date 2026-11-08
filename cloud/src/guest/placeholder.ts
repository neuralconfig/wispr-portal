// M0 placeholder guest page (kept until the M-b guest flow replaces it). It never calls the
// controller; it shows what the redirect delivered, for walled-garden and captive-sheet tests.

export const VERSION_PLACEHOLDER = "m0-placeholder";

// Same alphabet as wispr/security.py new_ref(): no 0/O/1/I/L/U, easy to read aloud.
const REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ";

export function newRef(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  // 256 % 30 != 0, so reject the top values to keep the choice uniform.
  let chars = "";
  let pool = bytes;
  let i = 0;
  while (chars.length < 8) {
    if (i >= pool.length) {
      pool = crypto.getRandomValues(new Uint8Array(8));
      i = 0;
    }
    const b = pool[i++];
    if (b < 240) chars += REF_ALPHABET[b % 30];
  }
  return `${chars.slice(0, 4)}-${chars.slice(4)}`;
}

export const SECURITY_HEADERS: Record<string, string> = {
  "Cache-Control": "no-store",
  "Content-Security-Policy":
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Strict-Transport-Security": "max-age=31536000",
};

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export function respond(body: string, contentType: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": contentType, ...SECURITY_HEADERS },
  });
}

export interface Seen {
  ref: string;
  env: string;
  host: string;
  ip: string;
  colo: string;
  tlsVersion: string;
  tlsCipher: string;
  httpProtocol: string;
  userAgent: string;
  params: [string, string][];
  time: string;
}

export function observe(request: Request, envName: string): Seen {
  const url = new URL(request.url);
  const cf = (request.cf ?? {}) as Record<string, unknown>;
  return {
    ref: newRef(),
    env: envName,
    host: url.host,
    ip: request.headers.get("CF-Connecting-IP") ?? "unknown",
    colo: String(cf.colo ?? ""),
    tlsVersion: String(cf.tlsVersion ?? ""),
    tlsCipher: String(cf.tlsCipher ?? ""),
    httpProtocol: String(cf.httpProtocol ?? ""),
    userAgent: request.headers.get("User-Agent") ?? "",
    params: [...url.searchParams.entries()],
    time: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  };
}

export function page(seen: Seen): string {
  const rows = seen.params.length
    ? seen.params
        .map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`)
        .join("")
    : `<tr><td colspan="2">No redirect parameters (this page was opened directly).</td></tr>`;
  const info: [string, string][] = [
    ["Reference", seen.ref],
    ["Host", seen.host],
    ["Your public IP", seen.ip],
    ["Cloudflare location", seen.colo],
    ["TLS", `${seen.tlsVersion} ${seen.tlsCipher}`.trim()],
    ["HTTP", seen.httpProtocol],
    ["Time (UTC)", seen.time],
  ];
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Guest Wi-Fi</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1B1F24; background: #F4F6F9; }
  header { background: #1B365D; color: #fff; padding: 16px; }
  header h1 { margin: 0; font-size: 1.25rem; }
  main { max-width: 640px; margin: 0 auto; padding: 16px; }
  .card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  th, td { text-align: left; padding: 4px 8px 4px 0; vertical-align: top; overflow-wrap: anywhere; }
  th { color: #4A5260; font-weight: 600; width: 40%; }
  p.note { color: #4A5260; font-size: 0.875rem; }
</style></head>
<body>
<header><h1>Guest Wi-Fi · test page</h1></header>
<main>
  <div class="card">
    <p><strong>This page loaded, so the portal host is reachable.</strong> This is a connectivity test page.
    It does not sign you in to the network.</p>
    <table>${info.map(([k, v]) => `<tr><th>${k}</th><td>${escapeHtml(v)}</td></tr>`).join("")}</table>
  </div>
  <div class="card">
    <h2 style="font-size:1rem;margin-top:0">Redirect parameters received</h2>
    <table>${rows}</table>
  </div>
  <p class="note">${escapeHtml(seen.env)} · ${VERSION_PLACEHOLDER} · Reference ${seen.ref}</p>
</main>
</body></html>`;
}

