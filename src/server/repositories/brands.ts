import "server-only";
import { unstable_cache } from "next/cache";
import { eq, sql } from "drizzle-orm";
import { getDb, schema } from "@/server/db";
import type { Brand } from "@/domain/types";
import { CATALOG_TAG } from "./rackets";

async function loadBrands(): Promise<Brand[]> {
  const db = await getDb();
  const rows = await db
    .select({
      id: schema.brands.id,
      slug: schema.brands.slug,
      name: schema.brands.name,
      country: schema.brands.country,
      description: schema.brands.description,
      websiteUrl: schema.brands.websiteUrl,
      logoUrl: schema.brands.logoUrl,
      racketCount: sql<number>`(select count(*) from products p where p.brand_id = "brands"."id" and p.status = 'published')`,
    })
    .from(schema.brands)
    .orderBy(schema.brands.name);
  return rows;
}

export const listBrands = unstable_cache(loadBrands, ["brands"], { tags: [CATALOG_TAG], revalidate: 3600 });

export async function getBrand(slug: string): Promise<Brand | null> {
  const all = await listBrands();
  return all.find((b) => b.slug === slug) ?? null;
}

export async function brandExists(slug: string): Promise<boolean> {
  const db = await getDb();
  const rows = await db.select({ id: schema.brands.id }).from(schema.brands).where(eq(schema.brands.slug, slug)).limit(1);
  return rows.length > 0;
}
