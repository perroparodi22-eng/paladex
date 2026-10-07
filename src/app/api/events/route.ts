/**
 * First-party analytics sink. Accepts small batches of whitelisted events
 * from the browser and stores them without any identifier: no cookies, no IP,
 * no user agent. Rate-limited per IP in memory (the IP itself is never stored).
 */
import { ANALYTICS_EVENTS } from "@/lib/analytics";
import { recordEvent } from "@/server/repositories/events";
import { rateLimit, clientKey } from "@/server/rate-limit";

const ALLOWED_PROPS = new Set([
  "slug",
  "slugs",
  "variant",
  "lod",
  "ms",
  "view",
  "key",
  "kind",
  "on",
  "length",
  "results",
  "count",
  "source",
  "filter",
  "value",
  "mode",
  "level",
  "top",
  "retailer",
]);

export async function POST(req: Request) {
  if (process.env.NEXT_PUBLIC_ANALYTICS_PROVIDER !== "first-party") return new Response(null, { status: 204 });
  const origin = req.headers.get("origin");
  const host = req.headers.get("host");
  if (origin && host && new URL(origin).host !== host) return new Response(null, { status: 403 });
  if (!rateLimit(`events:${clientKey(req)}`, 120, 10 * 60_000)) return new Response(null, { status: 429 });

  const raw = await req.text();
  if (raw.length > 16_000) return new Response(null, { status: 413 });
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return new Response(null, { status: 400 });
  }
  const events = (data as { events?: unknown })?.events;
  if (!Array.isArray(events)) return new Response(null, { status: 400 });

  for (const e of events.slice(0, 20)) {
    const name = (e as { name?: unknown })?.name;
    if (typeof name !== "string" || !(ANALYTICS_EVENTS as readonly string[]).includes(name)) continue;
    const props: Record<string, string | number | boolean> = {};
    const input = (e as { props?: Record<string, unknown> }).props ?? {};
    for (const [k, v] of Object.entries(input)) {
      if (!ALLOWED_PROPS.has(k)) continue;
      if (typeof v === "string") props[k] = v.slice(0, 120);
      else if (typeof v === "number" && Number.isFinite(v)) props[k] = v;
      else if (typeof v === "boolean") props[k] = v;
    }
    const path = typeof (e as { path?: unknown }).path === "string" ? ((e as { path: string }).path.slice(0, 200) as string) : null;
    await recordEvent(name, props, path);
  }
  return new Response(null, { status: 204 });
}
