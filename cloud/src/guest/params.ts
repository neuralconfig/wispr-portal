// Port of wispr/params.py: validation of the query string the controller appends to the portal URL.
// tests/vectors/params.json runs against both implementations (pytest and vitest) to keep them in step.

export const MAX_URL = 2048;

const ENC = /^ENC[0-9A-Fa-f]{8,256}$/;
const MAC =
  /^(?:[0-9A-Fa-f]{2}([:-]?)[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})$/;
const HOST = /^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{1,63})*\.?$/;
const TOKEN = /^[A-Za-z0-9._~:@%+=,/-]{1,256}$/;
const REASON = /^[A-Za-z][A-Za-z-]{0,63}$/;
const CTRL = /[\x00-\x1f\x7f]/;
const V4 = /^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

export const isMac = (v: string) => MAC.test(v);
export const isEnc = (v: string) => ENC.test(v);

function isV6(value: string): boolean {
  let s = value;
  const pct = s.indexOf("%");
  if (pct >= 0) {
    if (pct === s.length - 1 || s.slice(pct + 1).includes("/")) return false;
    s = s.slice(0, pct);
  }
  if (!/^[0-9A-Fa-f:.]+$/.test(s)) return false;
  let groups = 8;
  const lastColon = s.lastIndexOf(":");
  if (s.includes(".")) {
    if (!V4.test(s.slice(lastColon + 1))) return false;
    s = s.slice(0, lastColon + 1) + "0:0";
  }
  const halves = s.split("::");
  if (halves.length > 2) return false;
  const parts = (h: string) => (h === "" ? [] : h.split(":"));
  const head = parts(halves[0]);
  const tail = halves.length === 2 ? parts(halves[1]) : [];
  for (const g of [...head, ...tail]) if (!/^[0-9A-Fa-f]{1,4}$/.test(g)) return false;
  const n = head.length + tail.length;
  return halves.length === 2 ? n <= groups - 1 : n === groups;
}

/** Python ipaddress.ip_address() equivalent for the forms the controller sends. */
export function isIp(value: string): boolean {
  return V4.test(value) || (value.includes(":") && isV6(value));
}

export const isHost = (v: string) => isIp(v) || HOST.test(v);

/** Minimal urllib.parse.urlsplit: scheme, netloc → {username?, hostname}. Null on ValueError. */
function splitUrl(value: string): { scheme: string; hasUser: boolean; hostname: string } | null {
  const m = /^([A-Za-z][A-Za-z0-9+.-]*):(.*)$/s.exec(value);
  const scheme = m ? m[1].toLowerCase() : "";
  const rest = m ? m[2] : value;
  if (!rest.startsWith("//")) return { scheme, hasUser: false, hostname: "" };
  const after = rest.slice(2);
  const end = after.search(/[/?#]/);
  const netloc = end < 0 ? after : after.slice(0, end);
  // urlsplit raises on unbalanced brackets.
  if (netloc.includes("[") !== netloc.includes("]")) return null;
  const at = netloc.lastIndexOf("@");
  const hostport = at >= 0 ? netloc.slice(at + 1) : netloc;
  let hostname: string;
  if (hostport.startsWith("[")) {
    const close = hostport.indexOf("]");
    if (close < 0) return null;
    hostname = hostport.slice(1, close);
  } else {
    const colon = hostport.indexOf(":");
    hostname = colon >= 0 ? hostport.slice(0, colon) : hostport;
  }
  return { scheme, hasUser: at >= 0, hostname: hostname.toLowerCase() };
}

/** Reduce an nbiIP value to a bare, lower-case host, or null. */
export function normalizeHost(raw: string): string | null {
  const value = raw.trim();
  if (!value || value.length > 300) return null;
  let host: string;
  if (value.includes("://")) {
    const parts = splitUrl(value);
    if (!parts || !["http", "https"].includes(parts.scheme) || parts.hasUser) return null;
    host = parts.hostname;
  } else {
    host = value.split("/", 1)[0];
    if (host.startsWith("[")) host = host.slice(1).split("]", 1)[0];
    else if ((host.match(/:/g) ?? []).length === 1) host = host.split(":", 1)[0];
  }
  host = host.replace(/\.+$/, "").toLowerCase();
  return isHost(host) ? host : null;
}

/** The URL if it is an absolute http(s) URL with a host and no credentials, else null. */
export function safeHttpUrl(raw: string): string | null {
  const value = raw.trim();
  if (!value || value.length > MAX_URL || CTRL.test(value)) return null;
  const parts = splitUrl(value);
  if (!parts || !["http", "https"].includes(parts.scheme) || !parts.hostname || parts.hasUser) return null;
  return value;
}

const text = (max: number) => (v: string) => (v.length > max || CTRL.test(v) ? null : v);
const intRange = (lo: number, hi: number) => (v: string) =>
  /^\d{1,10}$/.test(v) && Number(v) >= lo && Number(v) <= hi ? v : null;
const ok = (pred: (v: string) => boolean) => (v: string) => (pred(v) ? v : null);

type Validator = (v: string) => string | null;

// name -> [validator, description]
export const KNOWN: Record<string, [Validator, string]> = {
  client_mac: [ok((v) => isEnc(v) || isMac(v)), "UE MAC (encrypted when the controller encrypts MAC/IP)"],
  uip: [ok((v) => isEnc(v) || isIp(v)), "UE IP (encrypted when the controller encrypts MAC/IP)"],
  nbiIP: [ok((v) => normalizeHost(v) !== null), "Controller NBI address (used only if it is in the allowlist)"],
  nbiIPv6: [ok(isIp), "Controller NBI IPv6 address"],
  mac: [ok(isMac), "AP MAC"],
  apip: [ok(isIp), "AP IP (ZD-style backup login)"],
  ssid: [text(32 * 4), "SSID"],
  wlanName: [text(128), "WLAN name"],
  url: [safeHttpUrl, "Original URL the guest asked for"],
  startUrl: [safeHttpUrl, "Start page from the portal profile"],
  reason: [ok((v) => REASON.test(v)), "Redirect reason (Un-Auth-Captive / Un-Auth-SSL-Captive)"],
  proxy: [ok((v) => v === "0" || v === "1"), "Browser uses a web proxy"],
  vlan: [intRange(0, 4094), "Client VLAN"],
  wlan: [intRange(0, 1_000_000), "WLAN ID"],
  sip: [ok((v) => normalizeHost(v) !== null), "Controller captive-portal FQDN"],
  dn: [ok((v) => normalizeHost(v) !== null), "Domain name"],
  zoneId: [ok((v) => TOKEN.test(v)), "Zone ID (3rd-party APs)"],
  zoneName: [ok((v) => TOKEN.test(v)), "Opaque zone token (7.1.1.3: <token>_<epoch ms>)"],
  lid: [text(253), "Location ID"],
  loc: [text(253), "Location name"],
  domain_name: [text(128), "SZ management domain (seen on 7.1.1.3)"],
  sshTunnelStatus: [ok((v) => v === "0" || v === "1"), "AP-to-controller tunnel up (1) or down (0)"],
};

export const REQUIRED = ["client_mac"];
const MAX_UNKNOWN = 20;
const CANONICAL = new Map(Object.keys(KNOWN).map((k) => [k.toLowerCase(), k]));

export interface RedirectParams {
  values: Record<string, string>;
  unknown: Record<string, string>;
  rejected: Record<string, string>;
  missing: string[];
  aliases: Record<string, string>;
  ok: boolean;
}

/** Same rules as parse_redirect(): case-insensitive names, repeated names rejected, values validated. */
export function parseRedirect(args: URLSearchParams): RedirectParams {
  const r: RedirectParams = { values: {}, unknown: {}, rejected: {}, missing: [], aliases: {}, ok: false };
  const names = [...new Set(args.keys())];
  for (let name of names) {
    const raws = args.getAll(name);
    if (raws.length !== 1) {
      r.rejected[name] = "repeated parameter";
      continue;
    }
    const raw = raws[0];
    const canon = CANONICAL.get(name.toLowerCase());
    if (canon !== undefined && canon !== name) {
      r.aliases[canon] = name;
      name = canon;
    }
    if (name in r.values || name in r.rejected) {
      delete r.values[name];
      r.rejected[name] = "repeated parameter";
      continue;
    }
    if (!(name in KNOWN)) {
      if (Object.keys(r.unknown).length < MAX_UNKNOWN && name.length <= 40) {
        r.unknown[name.slice(0, 40)] = text(200)(raw) ?? "(invalid)";
      }
      continue;
    }
    const value = raw.trim();
    if (!value) continue;
    const checked = KNOWN[name][0](value);
    if (checked === null) r.rejected[name] = "invalid format";
    else r.values[name] = checked;
  }
  for (const name of REQUIRED) {
    if (!(name in r.values) && !(name in r.rejected)) r.missing.push(name);
  }
  r.ok = r.missing.length === 0 && !REQUIRED.some((k) => k in r.rejected);
  return r;
}
