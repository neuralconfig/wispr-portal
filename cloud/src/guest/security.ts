// Port of wispr/security.py: reference IDs, CSRF tokens, response headers.

// No 0/O/1/I/L/U: easy to read aloud.
const REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ";

export function newRef(): string {
  let chars = "";
  while (chars.length < 8) {
    for (const b of crypto.getRandomValues(new Uint8Array(8))) {
      // 256 % 30 != 0: drop the top values so every character is equally likely.
      if (b < 240 && chars.length < 8) chars += REF_ALPHABET[b % 30];
    }
  }
  return `${chars.slice(0, 4)}-${chars.slice(4)}`;
}

export const REF_RE = /^[2-9A-HJKMNP-TV-Z]{4}-[2-9A-HJKMNP-TV-Z]{4}$/;

export function newCsrf(): string {
  const b = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function csrfOk(expected: string | null | undefined, given: string | null | undefined): boolean {
  if (!expected || !given) return false;
  const a = new TextEncoder().encode(expected);
  const b = new TextEncoder().encode(given);
  return a.byteLength === b.byteLength && crypto.subtle.timingSafeEqual(a, b);
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export const CSP =
  "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; " +
  "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";

const COMMON: Record<string, string> = {
  "Content-Security-Policy": CSP,
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Strict-Transport-Security": "max-age=31536000",
};

/** apply_headers(): no-store for pages, an hour of caching for theme assets. */
export function securityHeaders(staticAsset = false): Record<string, string> {
  return staticAsset
    ? { ...COMMON, "Cache-Control": "public, max-age=3600" }
    : { ...COMMON, "Cache-Control": "no-store", Pragma: "no-cache" };
}

export function respond(body: string | null, contentType: string, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(body, { status, headers: { "Content-Type": contentType, ...securityHeaders(), ...extra } });
}
