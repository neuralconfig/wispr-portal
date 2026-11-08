// IP and CIDR matching for the guest allowlist, plus bearer-token checks.

function parseV4(ip: string): bigint | null {
  const parts = ip.split(".");
  if (parts.length !== 4) return null;
  let out = 0n;
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const n = Number(p);
    if (n > 255) return null;
    out = (out << 8n) | BigInt(n);
  }
  return out;
}

function parseV6(ip: string): bigint | null {
  let s = ip.toLowerCase();
  const pct = s.indexOf("%");
  if (pct >= 0) s = s.slice(0, pct);
  // Embedded IPv4 (::ffff:1.2.3.4)
  const lastColon = s.lastIndexOf(":");
  if (s.includes(".") && lastColon >= 0) {
    const v4 = parseV4(s.slice(lastColon + 1));
    if (v4 === null) return null;
    s = `${s.slice(0, lastColon + 1)}${(v4 >> 16n).toString(16)}:${(v4 & 0xffffn).toString(16)}`;
  }
  const halves = s.split("::");
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(":") : [];
  const tail = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const missing = 8 - head.length - tail.length;
  if (halves.length === 1 ? missing !== 0 : missing < 1) return null;
  const groups = [...head, ...Array(halves.length === 2 ? missing : 0).fill("0"), ...tail];
  let out = 0n;
  for (const g of groups) {
    if (!/^[0-9a-f]{1,4}$/.test(g)) return null;
    out = (out << 16n) | BigInt(parseInt(g, 16));
  }
  return out;
}

export function parseIp(ip: string): { v: 4 | 6; n: bigint } | null {
  const v4 = parseV4(ip.trim());
  if (v4 !== null) return { v: 4, n: v4 };
  const v6 = parseV6(ip.trim());
  return v6 === null ? null : { v: 6, n: v6 };
}

/** True when ip equals one of the entries (an address or a CIDR). */
export function ipAllowed(ip: string, entries: string[]): boolean {
  const addr = parseIp(ip);
  if (!addr) return false;
  for (const entry of entries) {
    const [base, bitsRaw] = entry.split("/");
    const net = parseIp(base);
    if (!net || net.v !== addr.v) continue;
    const width = addr.v === 4 ? 32 : 128;
    const bits = bitsRaw === undefined ? width : Number(bitsRaw);
    if (!Number.isInteger(bits) || bits < 0 || bits > width) continue;
    const shift = BigInt(width - bits);
    if (net.n >> shift === addr.n >> shift) return true;
  }
  return false;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Constant-time check of "Authorization: Bearer <token>" against a stored SHA-256 hex. */
export async function bearerMatches(request: Request, expectedSha256: string | undefined): Promise<boolean> {
  if (!expectedSha256) return false;
  const header = request.headers.get("Authorization") ?? "";
  const m = /^Bearer ([A-Za-z0-9_\-.]{16,200})$/.exec(header);
  if (!m) return false;
  const got = new TextEncoder().encode(await sha256Hex(m[1]));
  const want = new TextEncoder().encode(expectedSha256.trim().toLowerCase());
  if (got.byteLength !== want.byteLength) return false;
  return crypto.subtle.timingSafeEqual(got, want);
}
