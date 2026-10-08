/**
 * Popularity = affiliate click-throughs (x3) + racket page views over the
 * last 30 days, from first-party data only. Zero until real traffic exists,
 * in which case "Most popular" falls back to featured and score.
 */
import "server-only";
import { unstable_cache } from "next/cache";
import { and, eq, gte, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";

async function load(): Promise<Record<string, number>> {
  const db = await getDb();
  const since = new Date(Date.now() - 30 * 86_400_000);
  const clicks = await db
    .select({ slug: schema.products.slug, n: sql<number>`count(*)` })
    .from(schema.affiliateClicks)
    .innerJoin(schema.products, eq(schema.products.id, schema.affiliateClicks.productId))
    .where(gte(schema.affiliateClicks.createdAt, since))
    .groupBy(schema.products.slug);
  const views = await db
    .select({ slug: sql<string>`json_extract(${schema.analyticsEvents.props}, '$.slug')`, n: sql<number>`count(*)` })
    .from(schema.analyticsEvents)
    .where(and(eq(schema.analyticsEvents.name, "racket_viewed"), gte(schema.analyticsEvents.createdAt, since)))
    .groupBy(sql`json_extract(${schema.analyticsEvents.props}, '$.slug')`);
  const out: Record<string, number> = {};
  for (const c of clicks) out[c.slug] = (out[c.slug] ?? 0) + c.n * 3;
  for (const v of views) if (v.slug) out[v.slug] = (out[v.slug] ?? 0) + v.n;
  return out;
}

export const getPopularity = unstable_cache(load, ["popularity"], { revalidate: 3600, tags: ["popularity"] });
