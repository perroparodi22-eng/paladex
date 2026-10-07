/**
 * Platform score helpers. Scores are Paladex evaluations on a 1–10 scale.
 * The weights below define the "overall" score and can be tuned in one place
 * (the methodology version in config/site.ts should change with them).
 */
import type { PlatformEvaluation, ScoreKey } from "@/domain/types";

export const SCORE_WEIGHTS: Record<ScoreKey, number> = {
  power: 0.17,
  control: 0.17,
  maneuverability: 0.15,
  forgiveness: 0.14,
  sweetSpot: 0.13,
  defense: 0.12,
  attack: 0.12,
};

export function overallScore(e: Pick<PlatformEvaluation, ScoreKey>): number {
  let total = 0;
  for (const key of Object.keys(SCORE_WEIGHTS) as ScoreKey[]) total += e[key] * SCORE_WEIGHTS[key];
  return Math.round(total * 10) / 10;
}

export function formatScore(n: number): string {
  return n.toFixed(1);
}
