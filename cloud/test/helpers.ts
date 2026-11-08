import { env, SELF } from "cloudflare:test";
import type { Env } from "../src/env";

export const E = env as unknown as Env & { TEST_CONNECTOR_TOKEN: string; TEST_EVENTS_TOKEN: string };
export const T = E;
export const LAB_IP = "70.40.100.79";

export function hubStub() {
  return E.HUB.get(E.HUB.idFromName("dha"));
}

type AcceptHandler = (args: any, rpcId: string, ws: WebSocket) => object | null | Promise<object | null>;

/** A scripted fake connector on a real WebSocket to the hub. An accept handler that returns
 *  null sends no reply (the test replies, or drops the socket, itself). */
export async function connectFake(
  opts: { ip?: string; token?: string; probe?: (host: string) => object; accept?: AcceptHandler } = {},
) {
  const res = await SELF.fetch("https://connector.test/v1/connect", {
    headers: {
      Upgrade: "websocket",
      Authorization: `Bearer ${opts.token ?? T.TEST_CONNECTOR_TOKEN}`,
      "CF-Connecting-IP": opts.ip ?? LAB_IP,
    },
  });
  const ws = res.webSocket;
  const rpcs: any[] = [];
  if (!ws) return { res, ws: null, received: [] as any[], rpcs, next: async () => null as any };
  ws.accept();
  const received: any[] = [];
  const waiters: ((m: any) => void)[] = [];
  ws.addEventListener("message", (e) => void onMessage(JSON.parse(e.data as string)));
  async function onMessage(msg: any) {
    if (msg.type === "rpc" && msg.op === "probe") {
      const result = opts.probe
        ? opts.probe(msg.args.host)
        : { reachable: true, code: 100, duration_ms: 80, tls: { version: "TLSv1.2" } };
      ws!.send(JSON.stringify({ type: "rpc_result", id: msg.id, ok: true, result: { host: msg.args.host, ...result } }));
      return;
    }
    if (msg.type === "rpc" && msg.op === "accept") {
      rpcs.push(msg);
      if (opts.accept) {
        const reply = await opts.accept(msg.args, msg.id, ws!);
        if (reply) ws!.send(JSON.stringify({ type: "rpc_result", id: msg.id, ...reply }));
      }
      return;
    }
    const w = waiters.shift();
    if (w) w(msg);
    else received.push(msg);
  }
  const next = () => (received.length ? Promise.resolve(received.shift()) : new Promise<any>((r) => waiters.push(r)));
  return { res, ws, received, rpcs, next };
}

export async function handshake(c: Awaited<ReturnType<typeof connectFake>>) {
  c.ws!.send(JSON.stringify({ type: "hello", protocol: 1, version: "0.1.0", env: "test", ceiling: { hosts: [] } }));
  const config = await c.next();
  c.ws!.send(JSON.stringify({ type: "config_applied", hosts: config.config.hosts, ca_source: "local", pin: "bd09" }));
  return config;
}

export async function settle(ms = 50) {
  // Let the hub process messages sent from the test side.
  await new Promise((r) => setTimeout(r, ms));
}
