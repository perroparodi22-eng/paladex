import Link from "next/link";
import type { Metadata } from "next";
import { listRacketSummaries, getRacket } from "@/server/repositories/rackets";
import { listBrands } from "@/server/repositories/brands";
import { HomeHero } from "@/components/home/HomeHero";
import { CourtZones } from "@/components/home/CourtZones";
import { ShowroomExperience } from "@/components/showroom/ShowroomExperience";
import { RacketCard } from "@/components/racket/RacketCard";
import { BrandTiles } from "@/components/catalog/BrandTiles";
import { Container } from "@/components/layout/Section";
import { Reveal } from "@/components/ui/Reveal";
import { Icon } from "@/components/ui/Icon";
import { MODEL_RANK } from "@/lib/catalog/filters";
import { brandTiles } from "@/lib/catalog/brand-tiles";
import { racketInertia } from "@/lib/racket-physics";
import { pageMetadata, websiteJsonLd, jsonLdString } from "@/lib/seo";
import { siteConfig } from "@/config/site";
import { getPopularity } from "@/server/repositories/popularity";
import { STYLE_COLLECTIONS, getCollection } from "@/lib/collections";

export const revalidate = 3600;

export const metadata: Metadata = pageMetadata({
  title: `${siteConfig.name}: ${siteConfig.tagline2}`,
  description: "Turn padel rackets in interactive 3D, browse them brand by brand, see where the sweet spot and balance sit, and find the racket that fits your game.",
  path: "/",
});

function SectionTitle({ id, title, intro, action }: { id: string; title: string; intro?: string; action?: { href: string; label: string } }) {
  return (
    <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
      <div className="max-w-2xl">
        <h2 id={id} className="display text-[clamp(2rem,4vw,3.25rem)]">
          {title}
        </h2>
        {intro && <p className="mt-4 text-[1.0625rem] leading-relaxed text-ink-2">{intro}</p>}
      </div>
      {action && (
        <Link href={action.href} className="btn btn-secondary btn-sm">
          {action.label} <Icon name="arrowRight" size={16} />
        </Link>
      )}
    </div>
  );
}

export default async function HomePage() {
  const [summaries, brands, popularity] = await Promise.all([listRacketSummaries(), listBrands(), getPopularity()]);
  const heroPick =
    [...summaries].sort((a, b) => MODEL_RANK[b.modelStatus] - MODEL_RANK[a.modelStatus] || Number(b.featured) - Number(a.featured))[0] ?? null;
  const hero = heroPick ? await getRacket(heroPick.slug) : null;

  const popular = [...summaries]
    .sort((a, b) => (popularity[b.slug] ?? 0) - (popularity[a.slug] ?? 0) || Number(b.featured) - Number(a.featured) || (b.scores?.overall ?? 0) - (a.scores?.overall ?? 0))
    .slice(0, 4);
  const showroom = [...summaries].sort((a, b) => MODEL_RANK[b.modelStatus] - MODEL_RANK[a.modelStatus] || Number(b.featured) - Number(a.featured)).slice(0, 10);
  const tiles = brandTiles(brands, summaries);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString(websiteJsonLd()) }} />

      {hero && (
        <HomeHero
          racket={{
            slug: hero.slug,
            fullName: hero.fullName,
            shape: hero.specs.shape,
            visual: hero.visual,
            imageUrl: hero.model?.posterUrl ?? hero.imageUrl,
            imageAlt: hero.imageAlt,
            model: hero.model,
            hotspots: [],
            annotations: hero.annotations,
            overlays: hero.overlays,
            surfaceFinish: hero.specs.surfaceFinish,
            inertia: racketInertia(hero.specs),
          }}
          racketHref={`/rackets/${hero.slug}`}
          caption={hero.fullName}
        />
      )}

      {/* ------------------------------------------------ Brands into rackets */}
      <section className="pt-24 sm:pt-32" aria-labelledby="brands-title">
        <Container>
          <Reveal>
            <SectionTitle id="brands-title" title="Start with a brand." intro="Choose a brand and its rackets line up, ready to turn in 3D." action={{ href: "/rackets", label: "All rackets" }} />
          </Reveal>
          <Reveal beat={1}>
            <BrandTiles brands={tiles} />
          </Reveal>
        </Container>
      </section>

      {/* ------------------------------------------------ Showroom */}
      <section className="pt-24 sm:pt-32" aria-labelledby="showroom-title">
        <Container>
          <Reveal>
            <SectionTitle
              id="showroom-title"
              title="The 3D showroom."
              intro="One stage, every racket. Pick one from the strip and drag it to look from any side."
              action={{ href: "/showroom", label: "Open the showroom" }}
            />
          </Reveal>
          <Reveal beat={1}>
            <ShowroomExperience rackets={showroom} compact />
          </Reveal>
        </Container>
      </section>

      {/* ------------------------------------------------ Popular */}
      <section className="pt-24 sm:pt-32" aria-labelledby="popular-title">
        <Container>
          <Reveal>
            <SectionTitle id="popular-title" title="Popular right now." action={{ href: "/rackets", label: "Browse all" }} />
          </Reveal>
          <div className="grid grid-cols-1 gap-4 xs:grid-cols-2 lg:grid-cols-4">
            {popular.map((r, i) => (
              <Reveal key={r.slug} beat={i} className="flex">
                <RacketCard racket={r} className="w-full" />
              </Reveal>
            ))}
          </div>
        </Container>
      </section>

      {/* ------------------------------------------------ Where you play */}
      <section className="pt-24 sm:pt-32" aria-labelledby="style-title">
        <Container className="grid items-center gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          <Reveal>
            <h2 id="style-title" className="display max-w-xl text-[clamp(2rem,4vw,3.25rem)]">
              Where do you win your points?
            </h2>
            <p className="mt-4 max-w-lg text-[1.0625rem] leading-relaxed text-ink-2">
              Where you stand on court says a lot about the racket you need. Tap your zone, or browse by style and level.
            </p>
            <div className="mt-8 flex flex-wrap gap-2">
              {STYLE_COLLECTIONS.map((slug) => {
                const c = getCollection(slug)!;
                return (
                  <Link key={slug} href={`/collections/${slug}`} className="chip">
                    {c.label}
                  </Link>
                );
              })}
              <Link href="/collections/under-200" className="chip">
                Under €200
              </Link>
            </div>
          </Reveal>
          <Reveal beat={1}>
            <CourtZones />
          </Reveal>
        </Container>
      </section>

      {/* ------------------------------------------------ Finder */}
      <section className="pt-24 sm:pt-32" aria-labelledby="finder-title">
        <Container>
          <Reveal className="stage-sky relative overflow-hidden rounded-[32px] border border-white/6 px-6 py-14 sm:px-12 sm:py-20">
            <div className="grid items-end gap-10 lg:grid-cols-[1.1fr_1fr]">
              <div>
                <h2 id="finder-title" className="display text-[clamp(2rem,4vw,3.25rem)]">
                  Not sure where to start?
                </h2>
                <p className="mt-4 max-w-xl text-[1.0625rem] leading-relaxed text-ink-2">
                  Eight quick questions about your level, your game and your budget. You get your best matches in 3D, with the reasons each one fits.
                </p>
              </div>
              <div>
                <p className="mb-3 text-sm font-medium text-ink-2">Start with your level</p>
                <div className="grid gap-2 sm:grid-cols-3">
                  {[
                    ["beginner", "Beginner", "Learning the basics"],
                    ["intermediate", "Intermediate", "Play regularly"],
                    ["advanced", "Advanced", "Strong technique"],
                  ].map(([v, label, sub]) => (
                    <Link
                      key={v}
                      href={`/finder?level=${v}`}
                      className="rounded-[18px] border border-white/10 bg-surface/70 p-4 transition-[border-color,background-color,transform] duration-300 hover:-translate-y-0.5 hover:border-white/30 hover:bg-surface"
                    >
                      <span className="block font-semibold">{label}</span>
                      <span className="block text-xs text-ink-2">{sub}</span>
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          </Reveal>
        </Container>
      </section>
    </>
  );
}
