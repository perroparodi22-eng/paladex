/**
 * Admin session: a compact HMAC-SHA256 signed token in an HttpOnly cookie.
 * Format: <expiry ms>.<random id>.<signature base64url>
 * Verified in proxy.ts (fast redirect) AND in every admin page and server
 * action (requireAdmin), so the proxy is never the only line of defence.
 */
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "paladex_admin";
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

function secret(): string | null {
  const s = process.env.ADMIN_SESSION_SECRET?.trim();
  return s && s.length >= 32 ? s : null;
}

export function adminConfigured(): boolean {
  return !!secret() && !!process.env.ADMIN_PASSWORD_HASH?.trim();
}

function sign(payload: string, key: string): string {
  return createHmac("sha256", key).update(payload).digest("base64url");
}

export function createSessionToken(): string | null {
  const key = secret();
  if (!key) return null;
  const payload = `${Date.now() + SESSION_TTL_MS}.${randomBytes(12).toString("base64url")}`;
  return `${payload}.${sign(payload, key)}`;
}

export function verifySessionToken(token: string | undefined | null): boolean {
  const key = secret();
  if (!key || !token) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [exp, id, sig] = parts;
  if (!/^\d{10,16}$/.test(exp) || Number(exp) < Date.now() || !id) return false;
  const expected = Buffer.from(sign(`${exp}.${id}`, key));
  const given = Buffer.from(sig);
  return expected.length === given.length && timingSafeEqual(expected, given);
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  };
}
