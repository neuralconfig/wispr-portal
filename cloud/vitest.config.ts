import { createHash } from "node:crypto";
import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

const sha = (s: string) => createHash("sha256").update(s).digest("hex");

export const TEST_CONNECTOR_TOKEN = "wpc_dha_testtoken0123456789";
export const TEST_EVENTS_TOKEN = "wpe_dha_testtoken0123456789";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          CONNECTOR_TOKEN_SHA256: sha(TEST_CONNECTOR_TOKEN),
          EVENTS_TOKEN_SHA256: sha(TEST_EVENTS_TOKEN),
          SZ_NBI_PASSWORD: "nbi-secret-test",
          SZ_GUEST_PASSWORD: "guest-secret-test",
          HEALTH_GRACE_S: "0",
          TEST_CONNECTOR_TOKEN,
          TEST_EVENTS_TOKEN,
        },
      },
    }),
  ],
});
