/**
 * The body of a racket page: the dominant 3D viewer beside the facts, scores,
 * specs, offers, review, photos and model provenance. Shared by the public
 * page and the admin preview, so a draft previews exactly as it will publish.
 */
import Link from "next/link";
import type { Racket } from "@/domain/types";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { Container } from "@/components/layout/Section";
import { SpecTable } from "@/components/racket/SpecTable";
import { WhereToBuy } from "@/components/racket/WhereToBuy";
import { Gallery, ModelInfo, ReviewBlock, RoundupBlock, ScoresPanel, WhoIsItFor } from "@/components/racket/RacketDetailSections";
import { ProvenanceBadge } from "@/components/racket/ProvenanceBadge";
import { Icon } from "@/components/ui/Icon";
import { BALANCE_INFO, HARDNESS_INFO, LEVEL_INFO, SHAPE_INFO, STYLE_INFO, VERIFICATION_INFO } from "@/domain/vocab";
import { formatPrice, formatWeight } from "@/lib/format";
import { racketInertia } from "@/lib/racket-physics";

export function RacketDetail({ racket: r, others }: { racket: Racket; others: Array<{ slug: string; label: string }> }) {
  const price = r.priceFrom ?? r.indicativePrice;
  const facts = [
    { k: "Shape", v: SHAPE_INFO[r.specs.shape].label },
    { k: "Weight", v: formatWeight(r.specs.weightMinG, r.specs.weightMaxG) },
    { k: "Balance", v: r.specs.balance ? BALANCE_INFO[r.specs.balance].label.split(" (")[0] : "—" },
    { k: "Feel", v: r.specs.hardness ? HARDNESS_INFO[r.specs.hardness].label : "—" },
  ];

  return (
    <Container className="grid gap-8 pb-10 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:gap-10">
      {/* The 3D viewer is the page's dominant element; it stays in view while the facts scroll. */}
      <div className="lg:sticky lg:top-[80px] lg:self-start">
        <div className="relative h-[62svh] min-h-[420px] overflow-hidden rounded-plate border border-ink/8 lg:h-[calc(100dvh-112px)] lg:max-h-[880px]">
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
              surfaceFinish: r.specs.surfaceFinish,
              inertia: racketInertia(r.specs),
            }}
            variant="page"
            loadStrategy="eager"
            bridge
            priorityPoster
            className="absolute inset-0"
          />
        </div>
      </div>

      <div className="min-w-0">
        <header>
          <p className="label">
            <Link href={`/brands/${r.brand.slug}`} className="hover:text-ink">
              {r.brand.name}
            </Link>
            {r.collection ? ` · ${r.collection} line` : ""}
            {r.year ? ` · ${r.year}` : ""}
          </p>
          <h1 className="display mt-2 text-[clamp(2.75rem,5.4vw,4.75rem)] mb-5">{r.name}</h1>
          {(r.proPlayers?.length ?? 0) > 0 && (
            <Link
              href="/pros"
              className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/12 bg-surface px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:border-white/25 hover:text-ink"
            >
              <Icon name="trophy" size={16} className="text-ball" />
              Played by{" "}
              <span className="font-semibold text-ink">{r.proPlayers.map((p) => p.name).join(" and ")}</span>
              <span className="text-ink-3">· {r.proPlayers[0].tour === "women" ? "women's" : "men's"} tour</span>
            </Link>
          )}
          <p className="mt-3 text-[1.0625rem] leading-relaxed text-ink/85">{r.shortDescription}</p>
          <div className="mt-4 flex flex-wrap gap-1.5">
            <ProvenanceBadge status={r.model?.status ?? "unavailable"} long />
            {r.levels.map((l) => (
              <span key={l} className="badge">
                {LEVEL_INFO[l].label}
              </span>
            ))}
            {r.styles.map((s) => (
              <span key={s} className="badge">
                {STYLE_INFO[s].label}
              </span>
            ))}
            <span className={r.specs.verification === "verified" ? "badge bg-ok/15 text-ok" : "badge badge-warn"} title={VERIFICATION_INFO[r.specs.verification].description}>
              Specs {VERIFICATION_INFO[r.specs.verification].label.toLowerCase()}
            </span>
          </div>
        </header>

        <dl className="mt-6 grid grid-cols-2 border-t border-ink/10 sm:grid-cols-4">
          {facts.map((f, i) => (
            <div key={f.k} className={`border-b border-ink/10 py-3 ${i % 2 ? "pl-4 sm:pl-4" : "pr-4"} ${i > 0 ? "sm:border-l sm:pl-4" : ""}`}>
              <dt className="label">{f.k}</dt>
              <dd className="num mt-0.5 text-lg font-semibold">{f.v}</dd>
            </div>
          ))}
        </dl>

        <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="label">{r.priceFrom ? "Best price" : price ? "Indicative price" : "Price"}</p>
            {price ? (
              <p className="num text-4xl font-bold leading-none">{formatPrice(price)}</p>
            ) : (
              <p className="title mt-1 text-2xl leading-none text-ink-2">Not listed yet</p>
            )}
            {r.scores && (
              <p className="mt-1 text-sm text-ink-2">
                Platform score <span className="num font-semibold text-ink">{r.scores.overall.toFixed(1)}</span>/10
                {r.userRating && ` · ★ ${r.userRating.average} (${r.userRating.count} reviews)`}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {r.roundup && (
              <a href="#reviews" className="btn btn-secondary">
                What reviewers say
              </a>
            )}
            <a href="#where-to-buy" className="btn btn-primary">
              Where to buy <Icon name="arrowRight" size={16} />
            </a>
          </div>
        </div>

        <p className="mt-8 leading-relaxed text-ink-2">{r.description}</p>

        <section className="mt-12" aria-labelledby="who">
          <h2 id="who" className="display text-4xl">
            Who is this racket for?
          </h2>
          <WhoIsItFor racket={r} />
        </section>

        {r.roundup && (
          <section id="reviews" className="mt-12 scroll-mt-24" aria-labelledby="reviews-title">
            <h2 id="reviews-title" className="display text-4xl mb-5">
              What reviewers say
            </h2>
            <RoundupBlock racket={r} />
          </section>
        )}

        <section className="mt-12" aria-labelledby="scores">
          <h2 id="scores" className="display text-4xl mb-5">
            Platform scores
          </h2>
          <ScoresPanel racket={r} />
        </section>

        <section className="mt-12" aria-labelledby="specs">
          <h2 id="specs" className="display text-4xl mb-5">
            Specifications
          </h2>
          <SpecTable racket={r} />
        </section>

        <section id="where-to-buy" className="mt-12 scroll-mt-24" aria-labelledby="buy">
          <h2 id="buy" className="display text-4xl mb-5">
            Where to buy
          </h2>
          <WhereToBuy racket={r} />
        </section>

        {r.review && (
          <section className="mt-12" aria-labelledby="review">
            <h2 id="review" className="display text-4xl mb-5">
              Our take
            </h2>
            <ReviewBlock racket={r} />
          </section>
        )}

        {r.images.length > 0 && (
          <section className="mt-12" aria-labelledby="photos">
            <h2 id="photos" className="display text-4xl mb-5">
              Photos
            </h2>
            <Gallery racket={r} />
          </section>
        )}

        <section className="mt-12" aria-labelledby="model">
          <h2 id="model" className="display text-4xl mb-5">
            About this 3D model
          </h2>
          <ModelInfo racket={r} />
        </section>
      </div>
    </Container>
  );
}
