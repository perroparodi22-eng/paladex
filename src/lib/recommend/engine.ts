/**
 * Racket Finder recommendation engine.
 *
 * Transparent, rules-based scoring: every racket gets a 0–1 fit per factor,
 * factors are weighted, and the weighted fit maps to a match percentage.
 * Each recommendation explains itself: reasons, strengths, drawbacks and,
 * when the visitor named their current racket, how it differs.
 *
 * Tune WEIGHTS or the factor functions to change behaviour; the tests in
 * engine.test.ts pin the important properties.
 */
import type { PlayerLevel, RacketShape, RacketSummary, ScoreKey } from "@/domain/types";
import { SHAPE_INFO, SCORE_INFO } from "@/domain/vocab";
import { formatPrice } from "@/lib/format";

export interface FinderAnswers {
  level: PlayerLevel;
  game: "defensive" | "balanced" | "aggressive";
  priority: "power" | "control" | "maneuverability" | "balance";
  shape: RacketShape | "any";
  weight: "light" | "medium" | "heavy" | "any";
  /** Maximum budget in EUR, or null for no limit. */
  budget: number | null;
  /** Elbow or shoulder discomfort: favour softer, head-light rackets. */
  armCare: boolean;
  /** Slug of the racket the visitor uses now (excluded from results, used for comparisons). */
  current: string | null;
}

export interface Recommendation {
  racket: RacketSummary;
  match: number;
  reasons: string[];
  strengths: string[];
  drawbacks: string[];
  versusCurrent: string[];
  factors: Record<FactorKey, number>;
}

type FactorKey = "level" | "game" | "priority" | "shape" | "weight" | "budget" | "comfort";

export const WEIGHTS: Record<FactorKey, number> = {
  level: 0.22,
  game: 0.18,
  priority: 0.2,
  shape: 0.12,
  weight: 0.08,
  budget: 0.12,
  comfort: 0.08,
};

const clamp01 = (n: number) => Math.max(0, Math.min(1, n));
/** Score 1–10 to 0–1, where 5 maps to 0 and 10 to 1. */
const unit = (s: number) => clamp01((s - 5) / 5);
const SHAPE_ORDER: RacketShape[] = ["round", "teardrop", "hybrid", "diamond"];
const LEVEL_ORDER: PlayerLevel[] = ["beginner", "intermediate", "advanced"];

function priceOf(r: RacketSummary): number | null {
  const m = r.priceFrom ?? r.indicativePrice;
  return m ? m.amountCents / 100 : null;
}
function midWeight(r: RacketSummary): number | null {
  if (r.weightMinG && r.weightMaxG) return (r.weightMinG + r.weightMaxG) / 2;
  return r.weightMinG ?? r.weightMaxG ?? null;
}

function factors(r: RacketSummary, a: FinderAnswers): Record<FactorKey, number> {
  const s = r.scores;
  const userLevel = LEVEL_ORDER.indexOf(a.level);
  const levelDistance = r.levels.length
    ? Math.min(...r.levels.map((l) => Math.abs(LEVEL_ORDER.indexOf(l) - userLevel)))
    : 1;
  let level = levelDistance === 0 ? 1 : levelDistance === 1 ? 0.5 : 0.1;
  // Demanding rackets are a poor fit for beginners even if tagged loosely.
  if (a.level === "beginner" && (r.balance === "high" || r.hardness === "hard" || r.shape === "diamond")) level *= 0.45;

  let game = 0.5;
  if (s) {
    if (a.game === "defensive") game = (unit(s.defense) * 0.45 + unit(s.control) * 0.3 + unit(s.forgiveness) * 0.25);
    else if (a.game === "aggressive") game = unit(s.attack) * 0.55 + unit(s.power) * 0.45;
    else game = clamp01(1 - Math.abs(s.attack - s.defense) / 4) * 0.5 + unit((s.attack + s.defense + s.control) / 3) * 0.5;
  }

  let priority = 0.5;
  if (s) {
    if (a.priority === "power") priority = unit(s.power);
    else if (a.priority === "control") priority = unit(s.control);
    else if (a.priority === "maneuverability") priority = unit(s.maneuverability);
    else priority = clamp01(1 - Math.abs(s.power - s.control) / 3) * 0.5 + unit((s.power + s.control) / 2) * 0.5;
  }

  let shape = 1;
  if (a.shape !== "any") {
    const d = Math.abs(SHAPE_ORDER.indexOf(r.shape) - SHAPE_ORDER.indexOf(a.shape));
    shape = d === 0 ? 1 : d === 1 ? 0.55 : d === 2 ? 0.2 : 0.05;
  }

  let weight = 1;
  const w = midWeight(r);
  if (a.weight !== "any" && w) {
    const target = a.weight === "light" ? 350 : a.weight === "medium" ? 362 : 372;
    weight = clamp01(1 - Math.abs(w - target) / 18);
  } else if (a.weight !== "any") {
    weight = 0.6;
  }

  let budget = 1;
  const p = priceOf(r);
  if (a.budget !== null) {
    if (p === null) budget = 0.5;
    else if (p <= a.budget) budget = 1;
    else budget = clamp01(1 - (p - a.budget) / (a.budget * 0.35));
  }

  let comfort = 1;
  if (a.armCare) {
    const soft = r.hardness === "soft" || r.hardness === "medium-soft" ? 1 : r.hardness === "medium" ? 0.7 : r.hardness ? 0.3 : 0.6;
    const light = r.balance === "low" || r.balance === "medium-low" ? 1 : r.balance === "medium" ? 0.75 : r.balance ? 0.3 : 0.6;
    comfort = soft * 0.55 + light * 0.45;
  }

  return { level, game, priority, shape, weight, budget, comfort };
}

function explain(r: RacketSummary, a: FinderAnswers, f: Record<FactorKey, number>, catalog: RacketSummary[]) {
  const reasons: string[] = [];
  const drawbacks: string[] = [];
  const s = r.scores;
  const p = priceOf(r);
  if (f.level >= 1) reasons.push(`Suits ${a.level} players like you`);
  else if (f.level < 0.3) drawbacks.push(`Aimed at ${r.levels.join(" / ") || "a different level"} players`);
  if (s) {
    const key: ScoreKey | null =
      a.priority === "power" ? "power" : a.priority === "control" ? "control" : a.priority === "maneuverability" ? "maneuverability" : null;
    if (key && f.priority >= 0.6) reasons.push(`Strong ${SCORE_INFO[key].label.toLowerCase()} (${s[key].toFixed(1)}/10), which is what you asked for`);
    if (!key && f.priority >= 0.6) reasons.push(`Power (${s.power.toFixed(1)}) and control (${s.control.toFixed(1)}) are well balanced`);
    if (key && f.priority < 0.35) drawbacks.push(`${SCORE_INFO[key].label} is not its strength (${s[key].toFixed(1)}/10)`);
    if (a.game === "aggressive" && f.game >= 0.65) reasons.push("Built to finish points overhead");
    if (a.game === "defensive" && f.game >= 0.65) reasons.push("Reliable from the back of the court");
    if (a.game === "balanced" && f.game >= 0.65) reasons.push("Equally comfortable attacking and defending");
  }
  if (a.shape !== "any") {
    if (f.shape >= 1) reasons.push(`${SHAPE_INFO[r.shape].label} shape, as you prefer`);
    else if (f.shape < 0.3) drawbacks.push(`${SHAPE_INFO[r.shape].label} shape, not the ${SHAPE_INFO[a.shape].label.toLowerCase()} you prefer`);
  }
  if (a.budget !== null && p !== null) {
    if (p <= a.budget) reasons.push(`Within your budget (from ${formatPrice(r.priceFrom ?? r.indicativePrice, { compact: true })})`);
    else drawbacks.push(`About €${Math.round(p - a.budget)} over your budget`);
  }
  if (a.armCare) {
    if (f.comfort >= 0.8) reasons.push("Softer, head-light feel that is kinder to the arm");
    else if (f.comfort < 0.45) drawbacks.push("Firm or head-heavy, which is less forgiving on a sore arm");
  }
  if (a.weight !== "any" && f.weight < 0.45) drawbacks.push(`Heavier or lighter than the ${a.weight} weight you prefer`);

  // Strengths relative to the catalog average.
  const strengths: string[] = [];
  if (s) {
    const keys: ScoreKey[] = ["power", "control", "maneuverability", "forgiveness", "sweetSpot", "defense", "attack"];
    const avg = (k: ScoreKey) => {
      const vals = catalog.map((c) => c.scores?.[k]).filter((v): v is number => typeof v === "number");
      return vals.reduce((x, y) => x + y, 0) / Math.max(1, vals.length);
    };
    const ranked = keys.map((k) => ({ k, d: s[k] - avg(k) })).sort((x, y) => y.d - x.d);
    for (const { k, d } of ranked.slice(0, 2)) if (d > 0.2) strengths.push(`${SCORE_INFO[k].label} ${s[k].toFixed(1)}`);
    const weakest = ranked[ranked.length - 1];
    if (weakest.d < -0.8 && drawbacks.length < 3) drawbacks.push(`Below-average ${SCORE_INFO[weakest.k].label.toLowerCase()} (${s[weakest.k].toFixed(1)})`);
  }
  return { reasons: reasons.slice(0, 4), strengths, drawbacks: drawbacks.slice(0, 3) };
}

function versus(r: RacketSummary, current: RacketSummary | undefined): string[] {
  if (!current?.scores || !r.scores) return [];
  const out: string[] = [];
  const keys: ScoreKey[] = ["power", "control", "maneuverability", "forgiveness"];
  for (const k of keys) {
    const d = r.scores[k] - current.scores[k];
    if (Math.abs(d) >= 0.5) out.push(`${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} ${SCORE_INFO[k].label.toLowerCase()}`);
  }
  if (r.shape !== current.shape) out.push(`${SHAPE_INFO[r.shape].label} instead of ${SHAPE_INFO[current.shape].label.toLowerCase()}`);
  return out.slice(0, 4);
}

export function recommend(catalog: RacketSummary[], a: FinderAnswers, limit = 6): Recommendation[] {
  const current = a.current ? catalog.find((r) => r.slug === a.current) : undefined;
  const results: Recommendation[] = [];
  for (const r of catalog) {
    if (current && r.slug === current.slug) continue;
    const f = factors(r, a);
    let total = 0;
    let weightSum = 0;
    for (const k of Object.keys(WEIGHTS) as FactorKey[]) {
      if (k === "comfort" && !a.armCare) continue;
      total += f[k] * WEIGHTS[k];
      weightSum += WEIGHTS[k];
    }
    const fit = total / weightSum;
    const match = Math.round(40 + 58 * Math.pow(fit, 1.15));
    const ex = explain(r, a, f, catalog);
    results.push({ racket: r, match, ...ex, versusCurrent: versus(r, current), factors: f });
  }
  return results.sort((x, y) => y.match - x.match || (y.racket.scores?.overall ?? 0) - (x.racket.scores?.overall ?? 0)).slice(0, limit);
}
