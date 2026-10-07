import type { Brand, RacketSummary } from "@/domain/types";
import type { BrandTile } from "@/components/catalog/BrandTiles";

/** One tile per brand that has rackets, shown by the brand's logo; most rackets first. */
export function brandTiles(brands: Brand[], rackets: RacketSummary[]): BrandTile[] {
  return brands
    .map((b) => ({
      slug: b.slug,
      name: b.name,
      count: rackets.filter((r) => r.brand.slug === b.slug).length,
      logoUrl: b.logoUrl,
    }))
    .filter((t) => t.count > 0)
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}
