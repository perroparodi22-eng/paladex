"use client";
/**
 * The 3D showroom: one live stage (a single WebGL context), a carousel of
 * rackets, brand and playing-style filters and an info panel. Selecting a
 * racket dims the floodlight, swaps the model in place and lights it again.
 * Neighbouring preview models are preloaded once the current one is shown.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayingStyle, RacketSummary } from "@/domain/types";
import { BALANCE_INFO, MODEL_STATUS_INFO, SHAPE_INFO, STYLE_INFO } from "@/domain/vocab";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { RacketPoster } from "@/components/racket/RacketPoster";
import { ProvenanceBadge } from "@/components/racket/ProvenanceBadge";
import { ScoreBar } from "@/components/racket/ScoreBar";
import { Icon } from "@/components/ui/Icon";
import { formatPrice, formatWeight } from "@/lib/format";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

export function ShowroomExperience({
  rackets,
  initialSlug,
  compact = false,
}: {
  rackets: RacketSummary[];
  initialSlug?: string;
  compact?: boolean;
}) {
  const [brand, setBrand] = useState<string | null>(null);
  const [style, setStyle] = useState<PlayingStyle | null>(null);
  const list = useMemo(
    () => rackets.filter((r) => (!brand || r.brand.slug === brand) && (!style || r.styles.includes(style))),
    [rackets, brand, style],
  );
  const [slug, setSlug] = useState(initialSlug ?? rackets[0]?.slug);
  const current = rackets.find((r) => r.slug === slug) ?? rackets[0];
  const carousel = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!compact) track("showroom_opened", { count: rackets.length });
  }, [compact, rackets.length]);

  const select = useCallback(
    (s: string) => {
      setSlug(s);
      track("showroom_model_selected", { slug: s });
      const el = carousel.current?.querySelector<HTMLElement>(`[data-slug="${s}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    },
    [],
  );

  // Preload the neighbours' preview models after the current one is shown.
  useEffect(() => {
    const idx = list.findIndex((r) => r.slug === current?.slug);
    const next = [list[idx + 1], list[idx - 1]].filter(Boolean);
    const t = window.setTimeout(async () => {
      const { preloadModel } = await import("@/components/three/model-loader");
      for (const r of next) if (r?.modelPreviewUrl) preloadModel(r.modelPreviewUrl);
    }, 2500);
    return () => window.clearTimeout(t);
  }, [current?.slug, list]);

  const step = (dir: 1 | -1) => {
    if (!list.length) return;
    const idx = list.findIndex((r) => r.slug === current?.slug);
    const next = list[(idx + dir + list.length) % list.length];
    if (next) select(next.slug);
  };

  if (!current) return <p className="text-ink-2">No rackets to show yet.</p>;
  const brands = [...new Map(rackets.map((r) => [r.brand.slug, r.brand.name])).entries()];
  const styles: PlayingStyle[] = ["power", "control", "all-round", "defensive", "aggressive"];
  const best = current.priceFrom ?? current.indicativePrice;
  const NameHeading = compact ? "h3" : "h2";

  return (
    <div className={cn("grid gap-4", compact ? "lg:grid-cols-[minmax(0,1fr)_340px]" : "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        {!compact && (
          <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Filter the showroom">
            <button type="button" className="chip" data-active={!brand && !style} onClick={() => (setBrand(null), setStyle(null))}>
              All
            </button>
            {brands.map(([b, name]) => (
              <button key={b} type="button" className="chip" data-active={brand === b} aria-pressed={brand === b} onClick={() => setBrand(brand === b ? null : b)}>
                {name}
              </button>
            ))}
            <span className="mx-1 w-px self-stretch bg-ink/10" aria-hidden />
            {styles.map((s) => (
              <button key={s} type="button" className="chip" data-active={style === s} aria-pressed={style === s} onClick={() => setStyle(style === s ? null : s)}>
                {STYLE_INFO[s].label}
              </button>
            ))}
          </div>
        )}
        <div className={cn("relative overflow-hidden rounded-[28px] shadow-lift", compact ? "h-[min(70vh,640px)]" : "h-[min(74vh,780px)]")}>
          <Racket3DViewer
            racket={{
              slug: current.slug,
              fullName: current.fullName,
              shape: current.shape,
              visual: current.visual,
              imageUrl: current.imageUrl,
              imageAlt: current.imageAlt,
              model: MODEL_STATUS_INFO[current.modelStatus].interactive
                ? { status: current.modelStatus, url: current.modelUrl, previewUrl: current.modelPreviewUrl, posterUrl: null, supportsExplode: true }
                : { status: "unavailable", url: null, previewUrl: null, posterUrl: null, supportsExplode: false },
            }}
            variant="showroom"
            loadStrategy="visible"
            className="absolute inset-0"
          />
        </div>
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="num text-sm text-ink-3" aria-live="polite">
            Racket {Math.max(1, list.findIndex((r) => r.slug === current.slug) + 1)} of {list.length || rackets.length}
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => step(-1)} className="btn btn-secondary btn-sm" aria-label="Previous racket">
              <Icon name="chevronLeft" size={16} /> Previous
            </button>
            <button type="button" onClick={() => step(1)} className="btn btn-secondary btn-sm" aria-label="Next racket">
              Next <Icon name="chevronRight" size={16} />
            </button>
          </div>
        </div>
        <ul
          ref={carousel}
          className="no-scrollbar mt-3 flex snap-x gap-2 overflow-x-auto pb-1"
          aria-label="Rackets in the showroom"
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") {
              e.preventDefault();
              step(1);
            }
            if (e.key === "ArrowLeft") {
              e.preventDefault();
              step(-1);
            }
          }}
        >
          {list.map((r) => (
            <li key={r.slug} data-slug={r.slug} className="snap-start">
              <button
                type="button"
                onClick={() => select(r.slug)}
                aria-pressed={r.slug === current.slug}
                aria-label={`Show ${r.fullName}`}
                className={cn(
                  "group relative flex h-36 w-28 flex-col items-center justify-end overflow-hidden rounded-xl border bg-surface p-2 transition-colors",
                  r.slug === current.slug ? "border-court ring-1 ring-court" : "border-ink/8 hover:border-ink/25",
                )}
              >
                <span className="absolute inset-x-2 bottom-9 top-2">
                  <RacketPoster racket={r} sizes="112px" className="absolute inset-0" />
                </span>
                <span className="relative z-10 w-full truncate text-center text-[0.6875rem] font-semibold leading-tight text-ink">{r.name}</span>
                <span className="relative z-10 w-full truncate text-center text-[0.625rem] text-ink-3">{r.brand.name}</span>
              </button>
            </li>
          ))}
          {!list.length && <li className="p-4 text-sm text-ink-2">No rackets match these filters.</li>}
        </ul>
      </div>

      <aside aria-live="polite" className="plate flex flex-col p-5">
        <div className="flex items-center justify-between gap-2">
          <p className="label">
            {current.brand.name}
            {current.year ? ` · ${current.year}` : ""}
          </p>
          <ProvenanceBadge status={current.modelStatus} />
        </div>
        {/* Under a section h2 on the homepage; directly under the page h1 on /showroom. */}
        <NameHeading className="display mt-2 text-[2.6rem]">{current.name}</NameHeading>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">{current.shortDescription}</p>
        <dl className="mt-4 grid grid-cols-2 border-t border-ink/8 text-sm">
          {[
            ["Shape", SHAPE_INFO[current.shape].label],
            ["Weight", formatWeight(current.weightMinG, current.weightMaxG)],
            ["Balance", current.balance ? BALANCE_INFO[current.balance].label.split(" (")[0] : "—"],
            ["Levels", current.levels.map((l) => l[0].toUpperCase() + l.slice(1)).join(", ") || "—"],
          ].map(([k, v], i) => (
            <div key={k} className={cn("border-b border-ink/8 py-2", i % 2 ? "border-l pl-3" : "pr-3")}>
              <dt className="text-xs text-ink-3">{k}</dt>
              <dd className="num text-ink">{v}</dd>
            </div>
          ))}
        </dl>
        {current.scores && (
          <div className="mt-4 space-y-2">
            <ScoreBar label="Power" value={current.scores.power} />
            <ScoreBar label="Control" value={current.scores.control} />
            <ScoreBar label="Maneuverability" value={current.scores.maneuverability} />
            <ScoreBar label="Forgiveness" value={current.scores.forgiveness} />
            <p className="pt-1 text-[0.6875rem] text-ink-3">Platform evaluation (sample), not a manufacturer measurement.</p>
          </div>
        )}
        <div className="mt-auto pt-5">
          <div className="flex items-end justify-between">
            <div>
              <p className="label">{current.priceFrom ? "Best price" : best ? "Indicative price" : "Price"}</p>
              {best ? <p className="num text-2xl font-bold">{formatPrice(best)}</p> : <p className="title text-xl text-ink-2">Not listed yet</p>}
            </div>
            {current.offerCount > 0 && <p className="text-xs text-ink-3">{current.offerCount} sample offers</p>}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Link href={`/rackets/${current.slug}`} className="btn btn-primary">
              View details
            </Link>
            <Link href={`/rackets/${current.slug}#where-to-buy`} className="btn btn-secondary">
              Where to buy
            </Link>
          </div>
          <div className="mt-2 flex justify-center">
          </div>
        </div>
      </aside>
    </div>
  );
}
