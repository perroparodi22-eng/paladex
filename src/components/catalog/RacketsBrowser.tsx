/**
 * Rackets and brands as one browsing flow: brand tiles first, then the
 * rackets of the chosen brand (or all of them), with search and filters.
 * Used by /rackets and by each brand's URL (which opens with that brand chosen).
 */
import { listRacketSummaries } from "@/server/repositories/rackets";
import { listBrands } from "@/server/repositories/brands";
import { getPopularity } from "@/server/repositories/popularity";
import type { CatalogFilters } from "@/lib/catalog/filters";
import { brandTiles } from "@/lib/catalog/brand-tiles";
import { CatalogExplorer } from "./CatalogExplorer";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { itemListJsonLd, jsonLdString } from "@/lib/seo";

export async function RacketsBrowser({ initial, title, crumbs }: { initial: CatalogFilters; title: string; crumbs: Array<{ name: string; href?: string }> }) {
  const [rackets, brands, popularity] = await Promise.all([listRacketSummaries(), listBrands(), getPopularity()]);
  const notes = Object.fromEntries(brands.map((b) => [b.slug, b.description]));
  return (
    <Container className="pb-16 pt-8 sm:pt-10">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString(itemListJsonLd(title, rackets)) }} />
      <Breadcrumbs items={crumbs} />
      <h1 className="display max-w-3xl text-[clamp(2.4rem,5vw,4rem)]">{title}</h1>
      <p className="mb-10 mt-4 max-w-2xl text-[1.0625rem] leading-relaxed text-ink-2">
        Choose a brand, then a racket. Every racket turns in 3D.{" "}
        <span className="text-ink-3">Specifications are sample data while the catalog is in development.</span>
      </p>
      <CatalogExplorer rackets={rackets} initial={initial} popularity={popularity} brandTiles={brandTiles(brands, rackets)} brandNotes={notes} />
    </Container>
  );
}
