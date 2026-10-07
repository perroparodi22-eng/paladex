/**
 * Affiliate redirects and click logging. Clicks store no personal data.
 */
import "server-only";
import { and, desc, eq, gte, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";
import { hostMatches, isPlaceholderLink, isSafeHttpsUrl } from "@/lib/urls";

export interface RedirectTarget {
  offerId: number;
  productId: number;
  productSlug: string;
  productName: string;
  retailerId: number;
  retailerName: string;
  isDemo: boolean;
  /** Where to send the visitor, or null when the link is a placeholder or unsafe. */
  destination: string | null;
  reason: "ok" | "placeholder" | "unsafe" | "inactive";
}

export async function resolveOffer(offerId: number): Promise<RedirectTarget | null> {
  const db = await getDb();
  const row = await db.query.offers.findFirst({
    where: eq(schema.offers.id, offerId),
    with: { retailer: true, product: { with: { brand: true } } },
  });
  if (!row) return null;
  const base = {
    offerId: row.id,
    productId: row.productId,
    productSlug: row.product.slug,
    productName: `${row.product.brand.name} ${row.product.name}`,
    retailerId: row.retailerId,
    retailerName: row.retailer.name,
    isDemo: row.isDemo || row.retailer.isDemo,
  };
  if (!row.active || !row.retailer.active || row.product.status !== "published") return { ...base, destination: null, reason: "inactive" };
  if (isPlaceholderLink(row.affiliateUrl)) return { ...base, destination: null, reason: "placeholder" };
  const url = row.affiliateUrl!.trim();
  // Only https, and only to the retailer's allow-listed domains (no open redirect).
  const allowed = row.retailer.allowedDomains;
  if (!isSafeHttpsUrl(url) || (allowed.length > 0 && !hostMatches(url, allowed))) return { ...base, destination: null, reason: "unsafe" };
  return { ...base, destination: url, reason: "ok" };
}

export async function recordClick(t: RedirectTarget, sourcePath: string | null) {
  const db = await getDb();
  await db.insert(schema.affiliateClicks).values({
    offerId: t.offerId,
    productId: t.productId,
    retailerId: t.retailerId,
    sourcePath: sourcePath?.slice(0, 200) ?? null,
    wasPlaceholder: t.reason !== "ok",
  });
}

export async function clickStats(days = 30) {
  const db = await getDb();
  const since = new Date(Date.now() - days * 86_400_000);
  const byProduct = await db
    .select({
      productId: schema.affiliateClicks.productId,
      name: sql<string>`(select b.name || ' ' || p.name from ${schema.products} p join ${schema.brands} b on b.id = p.brand_id where p.id = ${schema.affiliateClicks.productId})`,
      clicks: sql<number>`count(*)`,
      placeholder: sql<number>`sum(${schema.affiliateClicks.wasPlaceholder})`,
    })
    .from(schema.affiliateClicks)
    .where(gte(schema.affiliateClicks.createdAt, since))
    .groupBy(schema.affiliateClicks.productId)
    .orderBy(desc(sql`count(*)`));
  const byRetailer = await db
    .select({
      retailer: schema.retailers.name,
      clicks: sql<number>`count(*)`,
    })
    .from(schema.affiliateClicks)
    .innerJoin(schema.retailers, eq(schema.retailers.id, schema.affiliateClicks.retailerId))
    .where(and(gte(schema.affiliateClicks.createdAt, since)))
    .groupBy(schema.retailers.name)
    .orderBy(desc(sql`count(*)`));
  const recent = await db
    .select()
    .from(schema.affiliateClicks)
    .orderBy(desc(schema.affiliateClicks.createdAt))
    .limit(25);
  return { byProduct, byRetailer, recent };
}
