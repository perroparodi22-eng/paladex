import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { listRacketSummaries } from "@/server/repositories/rackets";
import { getPopularity } from "@/server/repositories/popularity";
import { COLLECTIONS, getCollection } from "@/lib/collections";
import { applyFilters, EMPTY_FILTERS } from "@/lib/catalog/filters";
import { CatalogExplorer } from "@/components/catalog/CatalogExplorer";
import { Breadcrumbs, Container, SectionHeading } from "@/components/layout/Section";
import { breadcrumbJsonLd, itemListJsonLd, jsonLdString, pageMetadata } from "@/lib/seo";

export const revalidate = 3600;

export function generateStaticParams() {
  return COLLECTIONS.map((c) => ({ slug: c.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const c = getCollection(slug);
  if (!c) return { title: "Collection not found" };
  return pageMetadata({ title: c.title, description: c.description, path: `/collections/${c.slug}` });
}

export default async function CollectionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const c = getCollection(slug);
  if (!c) notFound();
  const [all, popularity] = await Promise.all([listRacketSummaries(), getPopularity()]);
  const initial = { ...EMPTY_FILTERS, sort: c.sort ?? EMPTY_FILTERS.sort };
  const matching = applyFilters(all, { ...initial, ...c.filter }, popularity);
  return (
    <Container className="pb-16 pt-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdString([
            breadcrumbJsonLd([
              { name: "Home", path: "/" },
              { name: "Rackets", path: "/rackets" },
              { name: c.title, path: `/collections/${c.slug}` },
            ]),
            itemListJsonLd(c.title, matching),
          ]),
        }}
      />
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Rackets", href: "/rackets" }, { name: c.title }]} />
      <SectionHeading as="h1" title={c.title} intro={c.intro} />
      <nav aria-label="Other collections" className="no-scrollbar -mx-4 mb-8 flex gap-2 overflow-x-auto px-4">
        {COLLECTIONS.map((o) => (
          <Link key={o.slug} href={`/collections/${o.slug}`} className="chip shrink-0" data-active={o.slug === c.slug} aria-current={o.slug === c.slug ? "page" : undefined}>
            {o.label}
          </Link>
        ))}
      </nav>
      <CatalogExplorer rackets={all} initial={initial} popularity={popularity} basePath={`/collections/${c.slug}`} lockedFilters={c.filter} />
    </Container>
  );
}
