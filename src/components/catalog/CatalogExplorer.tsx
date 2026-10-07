"use client";
/**
 * The racket database: instant search, filters and sorting on the client,
 * mirrored into the URL (shareable, back-button friendly). The server renders
 * the same results first, so every view is crawlable and works without JS.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RacketSummary } from "@/domain/types";
import { BALANCE_INFO, HARDNESS_INFO, LEVEL_INFO, SHAPE_INFO, STYLE_INFO } from "@/domain/vocab";
import {
  activeFilterCount,
  applyFilters,
  EMPTY_FILTERS,
  facetCounts,
  serializeFilters,
  SORTS,
  type CatalogFilters,
  type SortKey,
} from "@/lib/catalog/filters";
import { RacketCard } from "@/components/racket/RacketCard";
import { FilterPanel } from "./FilterPanel";
import { BrandTiles, type BrandTile } from "./BrandTiles";
import { Dialog } from "@/components/ui/Dialog";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";
import { pluralize } from "@/lib/format";
import { COLLECTIONS } from "@/lib/collections";

export function CatalogExplorer({
  rackets,
  initial,
  popularity,
  basePath = "/rackets",
  lockedFilters,
  brandTiles,
  brandNotes,
}: {
  rackets: RacketSummary[];
  initial: CatalogFilters;
  popularity: Record<string, number>;
  basePath?: string;
  /** Collection pages pin some filters; they are applied but not shown as removable. */
  lockedFilters?: Partial<CatalogFilters>;
  /** When given, browsing starts from these brand tiles (brands and rackets as one flow). */
  brandTiles?: BrandTile[];
  /** Short brand descriptions, shown when one brand is chosen. */
  brandNotes?: Record<string, string>;
}) {
  const [filters, setFilters] = useState<CatalogFilters>(initial);
  const [sheet, setSheet] = useState(false);
  const firstSync = useRef(true);
  const effective = useMemo(() => ({ ...filters, ...lockedFilters }), [filters, lockedFilters]);
  const results = useMemo(() => applyFilters(rackets, effective, popularity), [rackets, effective, popularity]);
  const counts = useMemo(() => facetCounts(applyFilters(rackets, { ...EMPTY_FILTERS, ...lockedFilters, q: filters.q })), [rackets, lockedFilters, filters.q]);
  const brands = useMemo(() => [...new Map(rackets.map((r) => [r.brand.slug, r.brand.name])).entries()].map(([slug, name]) => ({ slug, name })).sort((a, b) => a.name.localeCompare(b.name)), [rackets]);
  const years = useMemo(() => [...new Set(rackets.map((r) => r.year).filter((y): y is number => !!y))].sort((a, b) => b - a), [rackets]);
  const active = activeFilterCount(filters);
  const brandMode = !!brandTiles?.length;
  const activeBrand = filters.brands.length === 1 ? filters.brands[0] : null;
  const activeBrandName = activeBrand ? (brands.find((b) => b.slug === activeBrand)?.name ?? activeBrand) : null;

  // Mirror state into the URL without a navigation.
  useEffect(() => {
    if (firstSync.current) {
      firstSync.current = false;
      return;
    }
    const qs = serializeFilters(filters);
    window.history.replaceState(null, "", qs ? `${basePath}?${qs}` : basePath);
  }, [filters, basePath]);

  useEffect(() => {
    if (!filters.q) return;
    const t = setTimeout(() => track("search_performed", { length: filters.q.length, results: results.length, source: "catalog" }), 800);
    return () => clearTimeout(t);
  }, [filters.q, results.length]);

  const update = useCallback((patch: Partial<CatalogFilters>, key: string) => {
    setFilters((f) => ({ ...f, ...patch }));
    track("filter_used", { filter: key });
  }, []);

  const chips: Array<{ label: string; clear: () => void }> = [];
  for (const b of brandMode ? [] : filters.brands) chips.push({ label: brands.find((x) => x.slug === b)?.name ?? b, clear: () => update({ brands: filters.brands.filter((x) => x !== b) }, "brand") });
  for (const s of filters.shapes) chips.push({ label: SHAPE_INFO[s].label, clear: () => update({ shapes: filters.shapes.filter((x) => x !== s) }, "shape") });
  for (const s of filters.levels) chips.push({ label: LEVEL_INFO[s].label, clear: () => update({ levels: filters.levels.filter((x) => x !== s) }, "level") });
  for (const s of filters.styles) chips.push({ label: STYLE_INFO[s].label, clear: () => update({ styles: filters.styles.filter((x) => x !== s) }, "style") });
  for (const s of filters.balances) chips.push({ label: `${BALANCE_INFO[s].label.split(" (")[0]} balance`, clear: () => update({ balances: filters.balances.filter((x) => x !== s) }, "balance") });
  for (const s of filters.hardness) chips.push({ label: `${HARDNESS_INFO[s].label} core`, clear: () => update({ hardness: filters.hardness.filter((x) => x !== s) }, "hardness") });
  if (filters.priceMin !== null || filters.priceMax !== null)
    chips.push({ label: `€${filters.priceMin ?? 0}–${filters.priceMax ?? "∞"}`, clear: () => update({ priceMin: null, priceMax: null }, "price") });
  if (filters.weightMin !== null || filters.weightMax !== null)
    chips.push({ label: `${filters.weightMin ?? ""}–${filters.weightMax ?? ""} g`, clear: () => update({ weightMin: null, weightMax: null }, "weight") });
  if (filters.yearMin !== null) chips.push({ label: `${filters.yearMin}+`, clear: () => update({ yearMin: null }, "year") });
  if (filters.minPower !== null) chips.push({ label: `Power ≥ ${filters.minPower}`, clear: () => update({ minPower: null }, "power") });
  if (filters.minControl !== null) chips.push({ label: `Control ≥ ${filters.minControl}`, clear: () => update({ minControl: null }, "control") });
  if (filters.minManeuverability !== null) chips.push({ label: `Maneuverability ≥ ${filters.minManeuverability}`, clear: () => update({ minManeuverability: null }, "maneuverability") });
  if (filters.model !== "any") chips.push({ label: filters.model === "none" ? "3D coming soon" : filters.model === "platform" ? "Real-design 3D" : "Interactive 3D", clear: () => update({ model: "any" }, "model") });

  const reset = () => setFilters({ ...EMPTY_FILTERS, sort: filters.sort });

  return (
    <>
      {brandMode && (
        <div className="mb-10">
          <BrandTiles brands={brandTiles!} active={activeBrand} allCount={rackets.length} onSelect={(slug) => update({ brands: slug ? [slug] : [] }, "brand")} />
          {activeBrand && (
            <div key={activeBrand} className="rise mt-8 max-w-3xl">
              <h2 className="display text-[clamp(1.8rem,3.4vw,2.6rem)]">{activeBrandName} rackets</h2>
              {brandNotes?.[activeBrand] && <p className="mt-3 leading-relaxed text-ink-2">{brandNotes[activeBrand]}</p>}
            </div>
          )}
        </div>
      )}
      {/* Keeps the heading outline in order (h1, h2, then the cards' h3) for screen readers. */}
      {!(brandMode && activeBrand) && <h2 className="sr-only">Rackets</h2>}
    <div className="grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="hidden lg:block" aria-label="Filters">
        <div className="plate sticky top-[92px] max-h-[calc(100dvh-110px)] overflow-y-auto p-5">
          <div className="mb-4 flex items-center justify-between">
            <p className="title text-lg">Filters</p>
            {active > 0 && (
              <button type="button" onClick={reset} className="text-sm text-court hover:underline">
                Clear all ({active})
              </button>
            )}
          </div>
          <FilterPanel filters={filters} counts={counts} brands={brands} years={years} onChange={update} hideBrands={brandMode} />
        </div>
      </aside>

      <div className="min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="relative flex-1">
            <span className="sr-only">Search rackets, brands or models</span>
            <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-2" />
            <input
              type="search"
              value={filters.q}
              onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value.slice(0, 80) }))}
              placeholder="Search rackets, brands or models…"
              className="field h-12 rounded-full pl-11 shadow-soft"
            />
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary flex-1 lg:hidden" onClick={() => setSheet(true)}>
              <Icon name="sliders" size={18} /> Filters{active ? ` (${active})` : ""}
            </button>
            <label className="relative flex-1 sm:flex-none">
              <span className="sr-only">Sort by</span>
              <select
                value={filters.sort}
                onChange={(e) => update({ sort: e.target.value as SortKey }, "sort")}
                className="field h-12 appearance-none rounded-full pl-4 pr-10 shadow-soft sm:w-60"
              >
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
              <Icon name="chevronDown" size={16} className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-ink-2" />
            </label>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2" aria-live="polite">
          <p className="mr-2 text-sm text-ink-2">
            <span className="num font-semibold text-ink">{results.length}</span> {results.length === 1 ? "racket" : "rackets"}
            {filters.sort === "popular" && <span className="text-ink-3"> · by recent views and click-throughs, then featured</span>}
          </p>
          {chips.map((c) => (
            <button key={c.label} type="button" onClick={c.clear} className="chip min-h-8 gap-1.5 border-transparent bg-court-tint text-court-deep hover:text-court-deep" aria-label={`Remove filter ${c.label}`}>
              {c.label} <Icon name="close" size={12} />
            </button>
          ))}
        </div>

        {results.length > 0 ? (
          <ul className="mt-6 grid grid-cols-1 gap-4 xs:grid-cols-2 xl:grid-cols-3">
            {results.map((r, i) => (
              <li key={r.slug} className="flex">
                <RacketCard racket={r} priority={i < 3} className="w-full" />
              </li>
            ))}
          </ul>
        ) : (
          <div className="card-sky mt-6 rounded-[28px] p-10 text-center">
            <p className="title text-3xl">No rackets match these filters</p>
            <p className="mx-auto mt-2 max-w-md text-ink-2">
              {filters.q ? `Nothing matches “${filters.q}” with these filters.` : "Try removing a filter or two."} You can also start from a collection.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <button type="button" className="btn btn-primary btn-sm" onClick={reset}>
                Clear all filters
              </button>
              {COLLECTIONS.slice(0, 4).map((c) => (
                <Link key={c.slug} href={`/collections/${c.slug}`} className="btn btn-secondary btn-sm">
                  {c.label}
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>

      <Dialog open={sheet} onClose={() => setSheet(false)} title="Filters" variant="sheet">
        <div className="px-5 pb-28 pt-4">
          <FilterPanel filters={filters} counts={counts} brands={brands} years={years} onChange={update} hideBrands={brandMode} />
        </div>
        <div className="sticky bottom-0 flex gap-2 border-t border-ink/8 bg-surface p-4">
          <button type="button" className="btn btn-ghost flex-1" onClick={reset} disabled={active === 0}>
            Clear all
          </button>
          <button type="button" className="btn btn-primary flex-[2]" onClick={() => setSheet(false)}>
            Show {pluralize(results.length, "racket")}
          </button>
        </div>
      </Dialog>
    </div>
    </>
  );
}
