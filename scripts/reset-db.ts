/**
 * Deletes the local SQLite database file so `npm run setup` can recreate it.
 * Refuses to touch anything that is not a local file database.
 */
import { existsSync, rmSync } from "node:fs";
import { loadEnv } from "./lib/env";

loadEnv();
const url = process.env.DATABASE_URL?.trim() || "file:./data/paladex.db";
if (!url.startsWith("file:")) {
  console.error(`refusing to reset a non-local database (${url.split("@").pop()})`);
  process.exit(1);
}
const file = url.replace(/^file:/, "");
for (const f of [file, `${file}-wal`, `${file}-shm`, `${file}-journal`]) {
  if (existsSync(f)) rmSync(f);
}
console.log(`removed ${file}`);
