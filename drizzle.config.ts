import { defineConfig } from "drizzle-kit";

/**
 * Local development uses a SQLite file (DATABASE_URL defaults to file:./data/paladex.db).
 * Production can point DATABASE_URL at Turso (libsql://...) with DATABASE_AUTH_TOKEN.
 */
export default defineConfig({
  dialect: "turso",
  schema: "./src/server/db/schema.ts",
  out: "./drizzle",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "file:./data/paladex.db",
    authToken: process.env.DATABASE_AUTH_TOKEN,
  },
});
