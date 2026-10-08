/**
 * Small in-memory fixed-window rate limiter. Fine for a single server; with
 * several instances or serverless, move it to Redis/Upstash behind the same API.
 */
import "server-only";

const buckets = new Map<string, { count: number; reset: number }>();

export function rateLimit(key: string, limit: number, windowMs: number): boolean {
  const now = Date.now();
  const b = buckets.get(key);
  if (!b || b.reset < now) {
    buckets.set(key, { count: 1, reset: now + windowMs });
    if (buckets.size > 5000) for (const [k, v] of buckets) if (v.reset < now) buckets.delete(k);
    return true;
  }
  b.count++;
  return b.count <= limit;
}

/** Forget a key's attempts, e.g. after a successful sign-in. */
export function resetRateLimit(key: string): void {
  buckets.delete(key);
}

/** Client key for rate limiting: the nearest proxy-reported address, never stored. */
export function clientKey(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  const ip = fwd ? fwd.split(",").map((s) => s.trim()).filter(Boolean).pop() : req.headers.get("x-real-ip");
  return ip || "local";
}
