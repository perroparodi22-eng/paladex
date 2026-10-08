"use client";
/**
 * Side-by-side data comparison. Best values are marked, differences can be
 * isolated, and every row stays plain HTML (crawlable on /compare/a-vs-b).
 */
import Link from "next/link";
import { useState } from "react";
import type { Racket } from "@/domain/types";
import { COMPARE_ROWS, highlight, type CompareRow } from "@/lib/compare";
import { CompareToggle } from "./CompareToggle";
import { cn } from "@/lib/cn";

const SERIES = ["#2343d6", "#f07a3e", "#11163a", "#0f9a83"];

export function CompareTable({ rackets }: { rackets: Racket[] }) {
  const [diffOnly, setDiffOnly] = useState(false);
  const groups = [...new Set(COMPARE_ROWS.map((r) => r.group))];
  const scoreBar = (row: CompareRow, r: Racket, color: string) => {
    const v = row.num?.(r);
    if (row.group !== "Platform scores" || v === null || v === undefined) return null;
    return <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-ink/8"><span className="gauge-fill block h-full rounded-full" style={{ width: `${Math.max(0, Math.min(10, v)) * 10}%`, background: color }} /></span>;
  };
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <label className="chip cursor-pointer gap-2">
          <input type="checkbox" className="h-4 w-4 accent-court" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)} />
          Show differences only
        </label>
        <p className="text-xs text-ink-3">
          <span className="text-ok">●</span> best value per row · scores are platform evaluations (sample)
        </p>
      </div>
      <div className="overflow-x-auto rounded-[24px] border border-ink/6 bg-surface shadow-soft">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <caption className="sr-only">Specification and score comparison</caption>
          <thead>
            <tr className="bg-surface">
              <th scope="col" className="sticky left-0 z-10 w-44 bg-surface p-3 pl-4 text-left text-[0.8125rem] font-semibold text-ink-2">
                Racket
              </th>
              {rackets.map((r, i) => (
                <th key={r.slug} scope="col" className="min-w-40 p-3 text-left align-top">
                  <span className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SERIES[i] }} aria-hidden />
                    <Link href={`/rackets/${r.slug}`} className="font-semibold text-ink hover:underline">
                      {r.fullName}
                    </Link>
                  </span>
                  <span className="mt-2 block">
                    <CompareToggle item={{ slug: r.slug, name: r.name, brand: r.brand.name }} />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          {groups.map((g) => {
            const rows = COMPARE_ROWS.filter((r) => r.group === g).filter((row) => !diffOnly || highlight(row, rackets).differs);
            if (!rows.length) return null;
            return (
              <tbody key={g}>
                <tr>
                  <th colSpan={rackets.length + 1} scope="colgroup" className="bg-surface-2/70 px-4 py-2 text-left text-[0.8125rem] font-semibold text-ink [--rond:100]">
                    {g}
                  </th>
                </tr>
                {rows.map((row) => {
                  const h = highlight(row, rackets);
                  return (
                    <tr key={row.key} className="border-t border-ink/8">
                      <th scope="row" className="sticky left-0 z-10 bg-surface p-3 pl-4 text-left align-top font-normal text-ink-2" title={row.hint}>
                        {row.label}
                      </th>
                      {rackets.map((r, i) => (
                        <td
                          key={r.slug}
                          className={cn("num p-3 align-top text-ink", h.best === i && "text-ok", h.worst === i && "text-ink/60")}
                        >
                          <span className="flex items-center gap-1.5">
                            {h.best === i && <span aria-label="best" className="text-ok">●</span>}
                            {row.text(r)}
                          </span>
                          {scoreBar(row, r, SERIES[i])}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}
