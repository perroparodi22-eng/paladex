/**
 * Admin password hashing with scrypt (Node's built-in crypto).
 * Stored format (no "$" so .env expansion never mangles it):
 *   scrypt:N:r:p:<salt base64url>:<hash base64url>
 */
import { randomBytes, scrypt as scryptCb, timingSafeEqual, type ScryptOptions } from "node:crypto";

function scrypt(password: string, salt: Buffer, keylen: number, opts: ScryptOptions): Promise<Buffer> {
  return new Promise((resolve, reject) =>
    scryptCb(password, salt, keylen, opts, (err, key) => (err ? reject(err) : resolve(key))),
  );
}

const KEYLEN = 64;

export async function hashPassword(password: string): Promise<string> {
  if (password.length < 12) throw new Error("Use at least 12 characters for the admin password.");
  const salt = randomBytes(16);
  const N = 32768;
  const r = 8;
  const p = 1;
  const key = await scrypt(password, salt, KEYLEN, { N, r, p, maxmem: 128 * 1024 * 1024 });
  return ["scrypt", N, r, p, salt.toString("base64url"), key.toString("base64url")].join(":");
}

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split(":");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const [, n, r, p, saltB64, hashB64] = parts;
  const expected = Buffer.from(hashB64, "base64url");
  if (expected.length !== KEYLEN) return false;
  try {
    const key = await scrypt(password, Buffer.from(saltB64, "base64url"), KEYLEN, {
      N: Number(n),
      r: Number(r),
      p: Number(p),
      maxmem: 128 * 1024 * 1024,
    });
    return timingSafeEqual(key, expected);
  } catch {
    return false;
  }
}
