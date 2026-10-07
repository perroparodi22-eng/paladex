import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getRacket, listPublishedSlugs, listRacketSummaries } from "@/server/repositories/rackets";
import { ViewerBridgeProvider } from "@/components/three/ViewerBridge";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { RacketCard } from "@/components/racket/RacketCard";
import { RacketDetail } from "@/components/racket/RacketDetail";
import { TrackView } from "@/components/racket/TrackView";
import { Icon } from "@/components/ui/Icon";
import { SHAPE_INFO } from "@/domain/vocab";
import { formatWeight } from "@/lib/format";
import { breadcrumbJsonLd, jsonLdString, pageMetadata, productJsonLd } from "@/lib/seo";

export const revalidate = 3600;
export const dynamicParams = true;

export async function generateStaticParams() {
  const slugs = await listPublishedSlugs();
  return slugs.map((s) => ({ slug: s.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const r = await getRacket(slug);
  if (!r) return { title: "Racket not found" };
  const shape = SHAPE_INFO[r.specs.shape].label.toLowerCase();
  return pageMetadata({
    title: `${r.fullName}${r.year ? ` (${r.year})` : ""}: 3D model, specs and prices`,
    description: `${r.fullName}: ${shape} padel racket, ${formatWeight(r.specs.weightMinG, r.specs.weightMaxG)}${r.specs.balance ? `, ${r.specs.balance} balance` : ""}. Turn it in 3D, see who it suits, compare it and find where to buy.`,
    path: `/rackets/${r.slug}`,
  });
}

export default async function RacketPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [racket, all] = await Promise.all([getRacket(slug), listRacketSummaries()]);
  if (!racket) notFound();
  const r = racket;
  const similar = all
    .filter((x) => x.slug !== r.slug && (x.shape === r.shape || x.styles.some((s) => r.styles.includes(s))))
    .sort((a, b) => Number(b.shape === r.shape) - Number(a.shape === r.shape) || (b.scores?.overall ?? 0) - (a.scores?.overall ?? 0))
    .slice(0, 3);
  const others = all.filter((x) => x.slug !== r.slug).map((x) => ({ slug: x.slug, label: x.fullName }));

  const jsonLd = [
    productJsonLd(r),
    breadcrumbJsonLd([
      { name: "Home", path: "/" },
      { name: "Rackets", path: "/rackets" },
      { name: r.brand.name, path: `/brands/${r.brand.slug}` },
      { name: r.name, path: `/rackets/${r.slug}` },
    ]),
  ];

  return (
    <ViewerBridgeProvider>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString(jsonLd) }} />
      <TrackView slug={r.slug} />
      <Container className="pt-6 sm:pt-8">
        <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Rackets", href: "/rackets" }, { name: r.brand.name, href: `/brands/${r.brand.slug}` }, { name: r.name }]} />
      </Container>

      <RacketDetail racket={r} others={others} />

      {similar.length > 0 && (
        <section className="pt-24" aria-labelledby="similar">
          <Container>
            <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
              <h2 id="similar" className="display text-[clamp(2rem,4vw,3.25rem)]">
                Similar rackets
              </h2>
              <Link href={`/rackets?brand=${r.brand.slug}`} className="btn btn-secondary btn-sm">
                More from {r.brand.name} <Icon name="arrowRight" size={16} />
              </Link>
            </div>
            <div className="grid grid-cols-1 gap-4 xs:grid-cols-2 lg:grid-cols-3">
              {similar.map((s) => (
                <RacketCard key={s.slug} racket={s} />
              ))}
            </div>
          </Container>
        </section>
      )}
    </ViewerBridgeProvider>
  );
}
