// Per-isolate cache of the guest allowlist (the connector's egress IP + tenant CIDRs).
import type { Env } from "../env";
import { ipAllowed } from "../net";

export const TENANT = "dha";

export function hub(env: Env) {
  return env.HUB.get(env.HUB.idFromName(TENANT));
}

// A page view costs one hub call per 15 s at most.
let allowCache: { at: number; env: string; entries: string[] } | null = null;
const ALLOW_TTL_MS = 15_000;

export async function guestAllowed(env: Env, ip: string): Promise<boolean> {
  if (!allowCache || allowCache.env !== env.ENVIRONMENT || Date.now() - allowCache.at > ALLOW_TTL_MS) {
    allowCache = { at: Date.now(), env: env.ENVIRONMENT, entries: await hub(env).allowlist() };
  }
  if (ipAllowed(ip, allowCache.entries)) return true;
  // A just-reconnected connector may have a new IP: re-read once before refusing.
  allowCache = { at: Date.now(), env: env.ENVIRONMENT, entries: await hub(env).allowlist() };
  return ipAllowed(ip, allowCache.entries);
}

export function resetAllowCache(): void {
  allowCache = null;
}

