/**
 * Comparison table definition and difference helpers.
 */
import type { Racket } from "@/domain/types";
import { BALANCE_INFO, HARDNESS_INFO, MODEL_STATUS_INFO, SCORE_INFO, SHAPE_INFO, SURFACE_INFO, levelsLabel, stylesLabel } from "@/domain/vocab";
import { formatPrice, formatWeight } from "@/lib/format";

export const MAX_COMPARE = 4;

export interface CompareRow {
  key: string;
  label: string;
  group: "Price" | "Specification" | "Platform scores" | "Fit" | "3D";
  /** Numeric value used for best/worst highlighting. */
  num?: (r: Racket) => number | null;
  text: (r: Racket) => string;
  better?: "higher" | "lower";
  hint?: string;
}

const score = (k: keyof typeof SCORE_INFO): CompareRow => ({
  key: k,
  label: SCORE_INFO[k].label,
  group: "Platform scores",
  num: (r) => r.evaluation?.[k] ?? null,
  text: (r) => (r.evaluation ? r.evaluation[k].toFixed(1) : "—"),
  better: "higher",
  hint: SCORE_INFO[k].meaning,
});

export const COMPARE_ROWS: CompareRow[] = [
  {
    key: "price",
    label: "Best price",
    group: "Price",
    num: (r) => (r.priceFrom ?? r.indicativePrice)?.amountCents ?? null,
    text: (r) => formatPrice(r.priceFrom ?? r.indicativePrice),
    better: "lower",
  },
  { key: "shape", label: "Shape", group: "Specification", text: (r) => SHAPE_INFO[r.specs.shape].label, hint: "Round = control, diamond = power." },
  {
    key: "weight",
    label: "Weight",
    group: "Specification",
    num: (r) => (r.specs.weightMinG && r.specs.weightMaxG ? (r.specs.weightMinG + r.specs.weightMaxG) / 2 : null),
    text: (r) => formatWeight(r.specs.weightMinG, r.specs.weightMaxG),
  },
  {
    key: "balance",
    label: "Balance",
    group: "Specification",
    text: (r) => (r.specs.balance ? `${BALANCE_INFO[r.specs.balance].label}${r.specs.balanceMm ? ` · ${r.specs.balanceMm} mm` : ""}` : "—"),
    hint: "Higher balance = more head weight for overheads.",
  },
  { key: "hardness", label: "Core feel", group: "Specification", text: (r) => (r.specs.hardness ? HARDNESS_INFO[r.specs.hardness].label : "—") },
  { key: "thickness", label: "Profile", group: "Specification", text: (r) => (r.specs.thicknessMm ? `${r.specs.thicknessMm} mm` : "—") },
  { key: "surface", label: "Surface", group: "Specification", text: (r) => (r.specs.surfaceFinish ? SURFACE_INFO[r.specs.surfaceFinish].label : "—") },
  { key: "face", label: "Face", group: "Specification", text: (r) => r.specs.faceMaterial ?? "—" },
  { key: "core", label: "Core", group: "Specification", text: (r) => r.specs.coreMaterial ?? "—" },
  { key: "frame", label: "Frame", group: "Specification", text: (r) => r.specs.frameMaterial ?? "—" },
  score("power"),
  score("control"),
  score("maneuverability"),
  score("forgiveness"),
  score("sweetSpot"),
  score("defense"),
  score("attack"),
  {
    key: "overall",
    label: "Overall",
    group: "Platform scores",
    num: (r) => r.evaluation?.overall ?? null,
    text: (r) => (r.evaluation ? r.evaluation.overall.toFixed(1) : "—"),
    better: "higher",
  },
  { key: "level", label: "Player level", group: "Fit", text: (r) => levelsLabel(r.levels) },
  { key: "style", label: "Playing style", group: "Fit", text: (r) => stylesLabel(r.styles) },
  { key: "model", label: "3D model", group: "3D", text: (r) => MODEL_STATUS_INFO[r.model?.status ?? "unavailable"].label },
];

/** Index of the best and worst value per row (null when not comparable or all equal). */
export function highlight(row: CompareRow, rackets: Racket[]): { best: number | null; worst: number | null; differs: boolean } {
  const texts = rackets.map((r) => row.text(r));
  const differs = new Set(texts).size > 1;
  if (!row.num || !row.better || rackets.length < 2) return { best: null, worst: null, differs };
  const vals = rackets.map((r) => row.num!(r));
  if (vals.some((v) => v === null)) return { best: null, worst: null, differs };
  const nums = vals as number[];
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  if (max === min) return { best: null, worst: null, differs: false };
  const best = nums.indexOf(row.better === "higher" ? max : min);
  const worst = nums.indexOf(row.better === "higher" ? min : max);
  return { best, worst, differs: true };
}

/** Plain-language summary of the biggest score differences between two rackets. */
export function differenceSummary(a: Racket, b: Racket): string[] {
  if (!a.evaluation || !b.evaluation) return [];
  const keys = ["power", "control", "maneuverability", "forgiveness", "sweetSpot", "defense", "attack"] as const;
  const diffs = keys
    .map((k) => ({ k, d: a.evaluation![k] - b.evaluation![k] }))
    .filter((x) => Math.abs(x.d) >= 0.5)
    .sort((x, y) => Math.abs(y.d) - Math.abs(x.d))
    .slice(0, 3);
  const out = diffs.map(({ k, d }) => {
    const winner = d > 0 ? a : b;
    const loser = d > 0 ? b : a;
    return `${winner.name} scores ${Math.abs(d).toFixed(1)} higher on ${SCORE_INFO[k].label.toLowerCase()} than ${loser.name}.`;
  });
  if (a.specs.shape !== b.specs.shape) {
    out.push(`${a.name} is a ${SHAPE_INFO[a.specs.shape].label.toLowerCase()} and ${b.name} is a ${SHAPE_INFO[b.specs.shape].label.toLowerCase()}, so their sweet spots sit at different heights.`);
  }
  return out;
}

export function comparePairSlug(a: string, b: string): string {
  return `${a}-vs-${b}`;
}

export function parsePairSlug(pair: string, known: string[]): [string, string] | null {
  for (const s of known) {
    if (pair.startsWith(`${s}-vs-`)) {
      const rest = pair.slice(s.length + 4);
      if (known.includes(rest)) return [s, rest];
    }
  }
  return null;
}
