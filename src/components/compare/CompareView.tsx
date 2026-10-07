/** Full comparison: summary sentences, 3D, and the data table. */
import Link from "next/link";
import type { Racket } from "@/domain/types";
import { differenceSummary } from "@/lib/compare";
import { Racket3DComparison } from "./Racket3DComparison";
import { CompareTable } from "./CompareTable";
import { Icon } from "@/components/ui/Icon";
import { GaugeRow } from "./NeedleGauge";
import { SCORE_INFO, SCORE_KEYS } from "@/domain/vocab";

const SERIES = ["#2343d6", "#f07a3e", "#11163a", "#0f9a83"];

export function CompareView({ rackets }: { rackets: Racket[] }) {
  const summary = rackets.length >= 2 ? differenceSummary(rackets[0], rackets[1]) : [];
  return (
    <div className="space-y-10">
      {summary.length > 0 && (
        <div className="lower-third max-w-3xl p-5 [animation:none]">
          <p className="mb-2 text-[0.9375rem] font-semibold text-white [--rond:100]">
            In short: {rackets[0].name} vs {rackets[1].name}
          </p>
          <ul className="space-y-1.5">
            {summary.map((s) => (
              <li key={s} className="flex gap-2 text-court-mist">
                <Icon name="arrowRight" size={16} className="mt-1 shrink-0 text-white" /> {s}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Racket3DComparison rackets={rackets} />
      {rackets.every((r) => r.evaluation) && (
        <section aria-labelledby="tape-title" className="plate p-5 sm:p-7">
          <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
            <h2 id="tape-title" className="display text-[clamp(1.8rem,3vw,2.4rem)]">
              Tale of the tape
            </h2>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {rackets.map((r, i) => (
                <li key={r.slug} className="flex items-center gap-2 font-semibold">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: SERIES[i] }} aria-hidden />
                  {r.name}
                </li>
              ))}
            </ul>
          </div>
          <GaugeRow
            className="lg:grid-cols-7"
            rows={SCORE_KEYS.map((k) => ({
              title: SCORE_INFO[k].label,
              needles: rackets.map((r, i) => ({ value: r.evaluation![k], color: SERIES[i], label: r.name })),
            }))}
          />
          <p className="mt-5 text-xs text-ink-3">Platform scores from our own sample evaluation, not manufacturer measurements.</p>
        </section>
      )}
      <section aria-labelledby="table-title">
        <h2 id="table-title" className="display text-4xl mb-5">
          Specs and scores side by side
        </h2>
        <CompareTable rackets={rackets} />
      </section>
      <div className="flex flex-wrap gap-2">
        {rackets.map((r) => (
          <Link key={r.slug} href={`/rackets/${r.slug}#where-to-buy`} className="btn btn-secondary btn-sm">
            Where to buy the {r.name}
          </Link>
        ))}
      </div>
    </div>
  );
}
