/**
 * First-party analytics sink: event name, whitelisted props, path, time.
 * No cookies, IPs, user agents or identifiers are stored.
 */
import "server-only";
import { desc, gte, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";

export async function recordEvent(name: string, props: Record<string, string | number | boolean>, path: string | null) {
  const db = await getDb();
  await db.insert(schema.analyticsEvents).values({ name, props, path });
}

export async function eventCounts(days = 30) {
  const db = await getDb();
  const since = new Date(Date.now() - days * 86_400_000);
  return db
    .select({ name: schema.analyticsEvents.name, n: sql<number>`count(*)` })
    .from(schema.analyticsEvents)
    .where(gte(schema.analyticsEvents.createdAt, since))
    .groupBy(schema.analyticsEvents.name)
    .orderBy(desc(sql`count(*)`));
}

export async function recentEvents(limit = 30) {
  const db = await getDb();
  return db.select().from(schema.analyticsEvents).orderBy(desc(schema.analyticsEvents.createdAt)).limit(limit);
}
