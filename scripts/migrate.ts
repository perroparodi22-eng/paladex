/**
 * Applies pending SQL migrations from /drizzle to DATABASE_URL.
 *   npm run db:migrate
 * After changing src/server/db/schema.ts, create a migration with
 *   npm run db:generate
 */
import { mkdirSync } from "node:fs";
import { migrate } from "drizzle-orm/libsql/migrator";
import { loadEnv } from "./lib/env";
import { databaseUrl, getDb } from "../src/server/db/connection";

async function main() {
  loadEnv();
  const url = databaseUrl();
  if (url.startsWith("file:")) mkdirSync("data", { recursive: true });
  const db = await getDb();
  await migrate(db, { migrationsFolder: "./drizzle" });
  console.log(`migrations applied to ${url.replace(/\/\/.*@/, "//***@")}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
