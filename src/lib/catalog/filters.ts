/**
 * Catalog filtering, search and sorting. Pure functions shared by the server
 * (initial render, crawlable) and the client (instant updates). Filter state
 * round-trips through the URL so every view is shareable.
 */
import type { Balance, Hardness, ModelStatus, PlayerLevel, PlayingStyle, RacketShape, RacketSummary } from "@/domain/types";
import { BALANCES, HARDNESSES, PLAYER_LEVELS, PLAYING_STYLES, RACKET_SHAPES } from "@/domain/types";
import { LEVEL_INFO, SHAPE_INFO, STYLE_INFO } from "@/domain/vocab";

export const SORTS = [
  { key: "popular", label: "Most popular" },
  { key: "rating", label: "Highest platform score" },
  { key: "price-asc", label: "Lowest price" },
  { key: "price-desc", label: "Highest price" },
  { key: "newest", label: "Newest" },
  { key: "power", label: "Best for power" },
  { key: "control", label: "Best for control" },
  { key: "value", label: "Best value" },
  { key: "3d", label: "Best 3D experience" },
] as const;
export type SortKey = (typeof SORTS)[number]["key"];

export interface CatalogFilters {
  q: string;
  brands: string[];
  shapes: RacketShape[];
  levels: PlayerLevel[];
  styles: PlayingStyle[];
  balances: Balance[];
  hardness: Hardness[];
  priceMin: number | null;
  priceMax: number | null;
  weightMin: number | null;
  weightMax: number | null;
  yearMin: number | null;
  minPower: number | null;
  minControl: number | null;
  minManeuverability: number | null;
  model: "any" | "interactive" | "platform" | "none";
  sort: SortKey;
}

export const EMPTY_FILTERS: CatalogFilters = {
  q: "",
  brands: [],
  shapes: [],
  levels: [],
  styles: [],
  balances: [],
  hardness: [],
  priceMin: null,
  priceMax: null,
  weightMin: null,
  weightMax: null,
  yearMin: null,
  minPower: null,
  minControl: null,
  minManeuverability: null,
  model: "any",
  sort: "popular",
};

type Params = URLSearchParams | Record<string, string | string[] | undefined>;

function read(p: Params, key: string): string | undefined {
  if (p instanceof URLSearchParams) return p.get(key) ?? undefined;
  const v = p[key];
  return Array.isArray(v) ? v[0] : v;
}
const list = <T extends string>(raw: string | undefined, allowed: readonly T[]): T[] =>
  (raw ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s): s is T => (allowed as readonly string[]).includes(s));
const num = (raw: string | undefined): number | null => {
  if (raw === undefined || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
};
const range = (raw: string | undefined): [number | null, number | null] => {
  if (!raw) return [null, null];
  const [a, b] = raw.split("-");
  return [num(a), num(b)];
};

export function parseFilters(p: Params): CatalogFilters {
  const [priceMin, priceMax] = range(read(p, "price"));
  const [weightMin, weightMax] = range(read(p, "weight"));
  const sort = read(p, "sort");
  const model = read(p, "model");
  return {
    q: (read(p, "q") ?? "").slice(0, 80),
    brands: (read(p, "brand") ?? "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter((s) => /^[a-z0-9-]{1,40}$/.test(s)),
    shapes: list(read(p, "shape"), RACKET_SHAPES),
    levels: list(read(p, "level"), PLAYER_LEVELS),
    styles: list(read(p, "style"), PLAYING_STYLES),
    balances: list(read(p, "balance"), BALANCES),
    hardness: list(read(p, "hardness"), HARDNESSES),
    priceMin,
    priceMax,
    weightMin,
    weightMax,
    yearMin: num(read(p, "year")),
    minPower: num(read(p, "power")),
    minControl: num(read(p, "control")),
    minManeuverability: num(read(p, "maneuver")),
    model: model === "interactive" || model === "platform" || model === "none" ? model : "any",
    sort: SORTS.some((s) => s.key === sort) ? (sort as SortKey) : "popular",
  };
}

export function serializeFilters(f: CatalogFilters): string {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.brands.length) p.set("brand", f.brands.join(","));
  if (f.shapes.length) p.set("shape", f.shapes.join(","));
  if (f.levels.length) p.set("level", f.levels.join(","));
  if (f.styles.length) p.set("style", f.styles.join(","));
  if (f.balances.length) p.set("balance", f.balances.join(","));
  if (f.hardness.length) p.set("hardness", f.hardness.join(","));
  if (f.priceMin !== null || f.priceMax !== null) p.set("price", `${f.priceMin ?? ""}-${f.priceMax ?? ""}`);
  if (f.weightMin !== null || f.weightMax !== null) p.set("weight", `${f.weightMin ?? ""}-${f.weightMax ?? ""}`);
  if (f.yearMin !== null) p.set("year", String(f.yearMin));
  if (f.minPower !== null) p.set("power", String(f.minPower));
  if (f.minControl !== null) p.set("control", String(f.minControl));
  if (f.minManeuverability !== null) p.set("maneuver", String(f.minManeuverability));
  if (f.model !== "any") p.set("model", f.model);
  if (f.sort !== "popular") p.set("sort", f.sort);
  return p.toString();
}

export function activeFilterCount(f: CatalogFilters): number {
  return (
    f.brands.length +
    f.shapes.length +
    f.levels.length +
    f.styles.length +
    f.balances.length +
    f.hardness.length +
    (f.priceMin !== null || f.priceMax !== null ? 1 : 0) +
    (f.weightMin !== null || f.weightMax !== null ? 1 : 0) +
    (f.yearMin !== null ? 1 : 0) +
    (f.minPower !== null ? 1 : 0) +
    (f.minControl !== null ? 1 : 0) +
    (f.minManeuverability !== null ? 1 : 0) +
    (f.model !== "any" ? 1 : 0)
  );
}

/* ---------------------------------------------------------------- search */

const normalize = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9.]+/g, " ")
    .trim();

export function searchText(r: RacketSummary): string {
  return normalize(
    [
      r.brand.name,
      r.name,
      r.fullName,
      r.year ?? "",
      SHAPE_INFO[r.shape].label,
      ...r.styles.map((s) => STYLE_INFO[s].label),
      ...r.levels.map((l) => LEVEL_INFO[l].label),
    ].join(" "),
  );
}

/** 0 = no match; higher is better. Every query token must match. */
export function searchScore(r: RacketSummary, query: string): number {
  const tokens = normalize(query).split(" ").filter(Boolean);
  if (!tokens.length) return 1;
  const hay = searchText(r);
  const words = hay.split(" ");
  let score = 0;
  for (const t of tokens) {
    if (words.includes(t)) score += 3;
    else if (words.some((w) => w.startsWith(t))) score += 2;
    else if (hay.includes(t)) score += 1;
    else return 0;
  }
  if (normalize(r.fullName).startsWith(normalize(query))) score += 3;
  return score;
}

/* --------------------------------------------------------------- filters */

export const MODEL_RANK: Record<ModelStatus, number> = { official: 5, licensed: 4, platform: 3, placeholder: 2, unavailable: 0 };

export function priceEur(r: RacketSummary): number | null {
  const m = r.priceFrom ?? r.indicativePrice;
  return m ? m.amountCents / 100 : null;
}

function midWeight(r: RacketSummary): number | null {
  if (r.weightMinG && r.weightMaxG) return (r.weightMinG + r.weightMaxG) / 2;
  return r.weightMinG ?? r.weightMaxG ?? null;
}

export function valueIndex(r: RacketSummary): number {
  const p = priceEur(r);
  if (!r.scores || !p) return 0;
  return r.scores.overall / Math.max(40, p) * 100;
}

export function applyFilters(all: RacketSummary[], f: CatalogFilters, popularity: Record<string, number> = {}): RacketSummary[] {
  const scored: Array<{ r: RacketSummary; s: number }> = [];
  for (const r of all) {
    const s = searchScore(r, f.q);
    if (!s) continue;
    if (f.brands.length && !f.brands.includes(r.brand.slug)) continue;
    if (f.shapes.length && !f.shapes.includes(r.shape)) continue;
    if (f.levels.length && !f.levels.some((l) => r.levels.includes(l))) continue;
    if (f.styles.length && !f.styles.some((st) => r.styles.includes(st))) continue;
    if (f.balances.length && (!r.balance || !f.balances.includes(r.balance))) continue;
    if (f.hardness.length && (!r.hardness || !f.hardness.includes(r.hardness))) continue;
    const price = priceEur(r);
    if (f.priceMin !== null && (price === null || price < f.priceMin)) continue;
    if (f.priceMax !== null && (price === null || price > f.priceMax)) continue;
    const w = midWeight(r);
    if (f.weightMin !== null && (w === null || w < f.weightMin)) continue;
    if (f.weightMax !== null && (w === null || w > f.weightMax)) continue;
    if (f.yearMin !== null && (r.year ?? 0) < f.yearMin) continue;
    if (f.minPower !== null && (r.scores?.power ?? 0) < f.minPower) continue;
    if (f.minControl !== null && (r.scores?.control ?? 0) < f.minControl) continue;
    if (f.minManeuverability !== null && (r.scores?.maneuverability ?? 0) < f.minManeuverability) continue;
    if (f.model === "interactive" && MODEL_RANK[r.modelStatus] === 0) continue;
    if (f.model === "platform" && MODEL_RANK[r.modelStatus] < MODEL_RANK.platform) continue;
    if (f.model === "none" && r.modelStatus !== "unavailable") continue;
    scored.push({ r, s });
  }
  /** dir -1 = highest first (the default), 1 = lowest first. */
  const by = (fn: (r: RacketSummary) => number, dir: 1 | -1 = -1) => (a: { r: RacketSummary }, b: { r: RacketSummary }) =>
    (fn(a.r) - fn(b.r)) * dir;
  const sorters: Record<SortKey, (a: { r: RacketSummary; s: number }, b: { r: RacketSummary; s: number }) => number> = {
    popular: (a, b) =>
      (popularity[b.r.slug] ?? 0) - (popularity[a.r.slug] ?? 0) || Number(b.r.featured) - Number(a.r.featured) || (b.r.scores?.overall ?? 0) - (a.r.scores?.overall ?? 0),
    rating: by((r) => r.scores?.overall ?? 0),
    "price-asc": (a, b) => (priceEur(a.r) ?? Infinity) - (priceEur(b.r) ?? Infinity),
    "price-desc": (a, b) => (priceEur(b.r) ?? -Infinity) - (priceEur(a.r) ?? -Infinity),
    newest: (a, b) => (b.r.year ?? 0) - (a.r.year ?? 0) || b.r.createdAt.localeCompare(a.r.createdAt),
    power: by((r) => r.scores?.power ?? 0),
    control: by((r) => r.scores?.control ?? 0),
    value: by(valueIndex),
    "3d": (a, b) => MODEL_RANK[b.r.modelStatus] - MODEL_RANK[a.r.modelStatus] || (b.r.scores?.overall ?? 0) - (a.r.scores?.overall ?? 0),
  };
  scored.sort((a, b) => (f.q ? b.s - a.s : 0) || sorters[f.sort](a, b));
  return scored.map((x) => x.r);
}

/** Facet counts for the filter UI (how many results each option would leave). */
export function facetCounts(all: RacketSummary[]) {
  const count = <T extends string>(values: T[][]) => {
    const m = new Map<T, number>();
    for (const vs of values) for (const v of vs) m.set(v, (m.get(v) ?? 0) + 1);
    return m;
  };
  return {
    brands: count(all.map((r) => [r.brand.slug])),
    shapes: count(all.map((r) => [r.shape])),
    levels: count(all.map((r) => r.levels)),
    styles: count(all.map((r) => r.styles)),
    balances: count(all.map((r) => (r.balance ? [r.balance] : []))),
    hardness: count(all.map((r) => (r.hardness ? [r.hardness] : []))),
  };
}
