import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { GUIDES, getGuide, type GuideBlock } from "@/content/guides";
import { getRacket, listRacketSummaries } from "@/server/repositories/rackets";
import { getCollection } from "@/lib/collections";
import { applyFilters, EMPTY_FILTERS } from "@/lib/catalog/filters";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { ShapeGhost } from "@/components/home/ShapeGhost";
import { RacketCard } from "@/components/racket/RacketCard";
import { SHAPE_INFO } from "@/domain/vocab";
import { formatDate } from "@/lib/format";
import { breadcrumbJsonLd, jsonLdString, pageMetadata } from "@/lib/seo";
import { siteConfig, siteUrl } from "@/config/site";

export const revalidate = 3600;

export function generateStaticParams() {
  return GUIDES.map((g) => ({ slug: g.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const g = getGuide(slug);
  if (!g) return { title: "Guide not found" };
  return pageMetadata({ title: g.title, description: g.description, path: `/guides/${g.slug}` });
}

async function Block({ block }: { block: GuideBlock }) {
  switch (block.type) {
    case "p":
      return <p>{block.text}</p>;
    case "h2":
      return <h2>{block.text}</h2>;
    case "h3":
      return <h3>{block.text}</h3>;
    case "ul":
      return (
        <ul>
          {block.items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      );
    case "callout":
      return (
        <aside className="not-prose plate my-6 p-5">
          <p className="label mb-1 text-court">{block.title}</p>
          <p className="text-ink/90">{block.text}</p>
        </aside>
      );
    case "shapes":
      return (
        <figure className="not-prose my-8 rounded-plate border border-ink/8 bg-surface p-5">
          <ShapeGhost a={block.a} b={block.b} labelA={SHAPE_INFO[block.a].label} labelB={SHAPE_INFO[block.b].label} />
          <figcaption className="mt-3 text-center text-sm text-ink-2">{block.caption}</figcaption>
        </figure>
      );
    case "racket3d": {
      const r = await getRacket(block.slug);
      if (!r) return null;
      return (
        <figure className="not-prose my-8">
          <div className="relative h-[60svh] min-h-[380px] overflow-hidden rounded-plate border border-ink/8">
            <Racket3DViewer
              racket={{
                slug: r.slug,
                fullName: r.fullName,
                shape: r.specs.shape,
                visual: r.visual,
                imageUrl: r.model?.posterUrl ?? r.imageUrl,
                imageAlt: r.imageAlt,
                model: r.model,
                hotspots: r.hotspots,
                annotations: r.annotations,
                overlays: r.overlays,
              }}
              variant="page"
              loadStrategy="visible"
              initialView={block.view}
              initialOverlays={block.overlays}
              className="absolute inset-0"
            />
          </div>
          <figcaption className="mt-2 text-sm text-ink-2">
            {block.caption}{" "}
            <Link href={`/rackets/${r.slug}`} className="text-court underline">
              {r.fullName}
            </Link>
          </figcaption>
        </figure>
      );
    }
    case "rackets": {
      const c = getCollection(block.collection);
      if (!c) return null;
      const list = applyFilters(await listRacketSummaries(), { ...EMPTY_FILTERS, ...c.filter, sort: c.sort ?? "rating" }).slice(0, block.limit);
      return (
        <figure className="not-prose my-8">
          <div className="grid grid-cols-1 gap-4 xs:grid-cols-2">
            {list.map((r) => (
              <RacketCard key={r.slug} racket={r} />
            ))}
          </div>
          <figcaption className="mt-2 text-sm text-ink-2">{block.caption}</figcaption>
        </figure>
      );
    }
    case "links":
      return (
        <div className="not-prose my-8 flex flex-wrap gap-2">
          {block.items.map((l) => (
            <Link key={l.href} href={l.href} className="btn btn-secondary btn-sm">
              {l.label}
            </Link>
          ))}
        </div>
      );
  }
}

export default async function GuidePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const g = getGuide(slug);
  if (!g) notFound();
  const others = GUIDES.filter((x) => x.slug !== g.slug).slice(0, 3);
  const article = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: g.title,
    description: g.description,
    dateModified: g.updated,
    author: { "@type": "Organization", name: siteConfig.name },
    mainEntityOfPage: siteUrl(`/guides/${g.slug}`),
  };
  return (
    <Container className="pb-16 pt-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdString([
            article,
            breadcrumbJsonLd([
              { name: "Home", path: "/" },
              { name: "Guides", path: "/guides" },
              { name: g.title, path: `/guides/${g.slug}` },
            ]),
          ]),
        }}
      />
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Guides", href: "/guides" }, { name: g.title }]} />
      <article className="mx-auto max-w-3xl">
        <header>
          <h1 className="display text-[clamp(2.5rem,6vw,4.75rem)]">{g.title}</h1>
          <p className="mt-4 text-lg leading-relaxed text-ink/85">{g.description}</p>
          <p className="mt-3 text-sm text-ink-3">
            {g.minutes} min read · Updated {formatDate(g.updated)}
          </p>
        </header>
        <div className="prose mt-8">
          {g.blocks.map((b, i) => (
            <Block key={i} block={b} />
          ))}
        </div>
      </article>
      <aside className="mx-auto mt-16 max-w-3xl" aria-labelledby="more">
        <h2 id="more" className="display text-3xl">
          More guides
        </h2>
        <ul className="mt-4 divide-y divide-ink/8 border-y border-ink/8">
          {others.map((o) => (
            <li key={o.slug}>
              <Link href={`/guides/${o.slug}`} className="block py-3 hover:text-court">
                {o.title}
              </Link>
            </li>
          ))}
        </ul>
      </aside>
    </Container>
  );
}
