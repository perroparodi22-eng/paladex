import { listRacketSummaries } from "@/server/repositories/rackets";
import { listBrands } from "@/server/repositories/brands";
import { COLLECTIONS } from "@/lib/collections";
import { GUIDES } from "@/content/guides";
import { SHAPE_INFO, STYLE_INFO, LEVEL_INFO } from "@/domain/vocab";
import type { SearchIndex } from "@/components/search/SearchDialog";

export const revalidate = 3600;

export async function GET() {
  const [rackets, brands] = await Promise.all([listRacketSummaries(), listBrands()]);
  const body: SearchIndex = {
    rackets: rackets.map((r) => ({
      slug: r.slug,
      name: r.name,
      brand: r.brand.name,
      meta: [SHAPE_INFO[r.shape].label, r.year, r.levels.map((l) => LEVEL_INFO[l].label).join("/")].filter(Boolean).join(" · "),
      terms: [r.year, SHAPE_INFO[r.shape].label, ...r.styles.map((s) => STYLE_INFO[s].label), ...r.levels, r.hardness ?? "", r.balance ?? ""].join(" "),
    })),
    brands: brands.map((b) => ({ slug: b.slug, name: b.name, count: b.racketCount ?? 0 })),
    collections: COLLECTIONS.map((c) => ({ slug: c.slug, title: c.title })),
    guides: GUIDES.map((g) => ({ slug: g.slug, title: g.title })),
  };
  return Response.json(body, { headers: { "Cache-Control": "public, max-age=300, stale-while-revalidate=3600" } });
}
