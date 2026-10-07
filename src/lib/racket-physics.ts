/**
 * How long a flicked racket keeps turning in the 3D viewer (0..1). A heavier,
 * head-heavy racket carries more momentum than a light, even-balanced one,
 * so the replay "feels" like the racket. Illustrative, not a measurement.
 */
import type { Balance } from "@/domain/types";

const BALANCE_BIAS: Record<Balance, number> = { low: -1, "medium-low": -0.5, medium: 0, "medium-high": 0.5, high: 1 };

export function racketInertia(specs: { balance: Balance | null; balanceMm?: number | null; weightMinG?: number | null; weightMaxG?: number | null }): number {
  const balance = specs.balanceMm ? (specs.balanceMm - 262) / 12 : BALANCE_BIAS[specs.balance ?? "medium"];
  const weight = specs.weightMaxG ?? specs.weightMinG;
  const w = weight ? (weight - 360) / 20 : 0;
  return Math.max(0, Math.min(1, 0.5 + balance * 0.28 + w * 0.12));
}
