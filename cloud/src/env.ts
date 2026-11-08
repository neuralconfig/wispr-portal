import type { TenantHub } from "./hub/tenant-hub";

export interface Env {
  ENVIRONMENT: string;
  GUEST_HOST: string;
  API_HOST: string;
  CONNECTOR_HOST: string;
  HUB: DurableObjectNamespace<TenantHub>;
  // Secrets (wrangler secret put … --env <env>). Token secrets hold the SHA-256 hex of the token.
  CONNECTOR_TOKEN_SHA256?: string;
  EVENTS_TOKEN_SHA256?: string;
  SZ_NBI_PASSWORD?: string;
  SZ_GUEST_PASSWORD?: string;
  // Dev-only (ENVIRONMENT=dev): JSON merged over tenants/dha.json, for local end-to-end runs.
  TENANT_OVERRIDE?: string;
  // Test-only override of the tenant's reconnect grace (seconds).
  HEALTH_GRACE_S?: string;
}
