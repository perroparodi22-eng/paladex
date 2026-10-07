/**
 * Database connection (libSQL). Shared by the app (through ./index.ts, which
 * adds the server-only guard) and by the CLI scripts (migrate, seed).
 *
 * DATABASE_URL:
 *   file:./data/paladex.db           local SQLite file (default)
 *   libsql://<db>.turso.io           Turso, with DATABASE_AUTH_TOKEN
 *
 * On a serverless host (AWS Lambda, which Netlify Functions run on) the
 * bundled database file is read-only, so on first use it is copied to the
 * temp folder and opened there. Writes (clicks, events) then last only as long
 * as that server instance. DATABASE_TEMPLATE optionally names the file to copy
 * when DATABASE_URL already points into the temp folder.
 */
import { copyFileSync, existsSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createClient, type Client } from "@libsql/client";
import { drizzle, type LibSQLDatabase } from "drizzle-orm/libsql";
import * as schema from "./schema";

export type Db = LibSQLDatabase<typeof schema>;

const g = globalThis as unknown as { __paladex?: { client: Client; db: Db; ready: Promise<void> } };

/** True inside a serverless function (read-only code bundle, writable temp folder). */
const SERVERLESS = !!(process.env.AWS_LAMBDA_FUNCTION_NAME || process.env.LAMBDA_TASK_ROOT);

export function databaseUrl(): string {
  return process.env.DATABASE_URL?.trim() || "file:./data/paladex.db";
}

/** Returns a URL the server can write to, copying the bundled database into the temp folder when needed. */
function writableUrl(url: string): string {
  if (!url.startsWith("file:")) return url;
  const file = url.slice("file:".length);
  const template = process.env.DATABASE_TEMPLATE?.trim();
  const tmp = path.resolve(os.tmpdir());
  const inTmp = path.resolve(file).startsWith(tmp + path.sep) || file.startsWith("/tmp/");
  if (!template && (!SERVERLESS || inTmp)) return url;
  const target = inTmp ? file : path.join(tmp, path.basename(file));
  if (!existsSync(target)) {
    const wanted = template || file;
    const roots = [process.cwd(), process.env.LAMBDA_TASK_ROOT].filter((r): r is string => !!r);
    const source = path.isAbsolute(wanted) && existsSync(wanted) ? wanted : roots.map((r) => path.resolve(r, wanted)).find((p) => existsSync(p));
    if (!source) throw new Error(`Database file not found: ${wanted} (looked in ${roots.join(", ")})`);
    copyFileSync(source, target);
    // Anything still in the write-ahead log belongs to the copy too.
    if (existsSync(`${source}-wal`) && statSync(`${source}-wal`).size > 0) copyFileSync(`${source}-wal`, `${target}-wal`);
  }
  return `file:${target}`;
}

function connect() {
  const url = writableUrl(databaseUrl());
  const client = createClient({ url, authToken: process.env.DATABASE_AUTH_TOKEN?.trim() || undefined });
  const db = drizzle(client, { schema });
  const ready = (async () => {
    if (url.startsWith("file:")) {
      // WAL is faster for concurrent reads, but never worth failing over (e.g. on a read-only disk).
      await client.execute("PRAGMA journal_mode = WAL").catch(() => undefined);
      await client.execute("PRAGMA busy_timeout = 5000");
    }
    await client.execute("PRAGMA foreign_keys = ON");
  })();
  return { client, db, ready };
}

/** Lazily connected singleton (survives hot reloads in development). */
export async function getDb(): Promise<Db> {
  if (!g.__paladex) g.__paladex = connect();
  try {
    await g.__paladex.ready;
  } catch (e) {
    // Don't keep a broken connection for the life of the server: retry on the next request.
    g.__paladex = undefined;
    throw e;
  }
  return g.__paladex.db;
}

export function getClient(): Client {
  if (!g.__paladex) g.__paladex = connect();
  return g.__paladex.client;
}

export { schema };
