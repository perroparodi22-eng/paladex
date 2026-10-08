"use client";
/** Choose 2–4 rackets to compare (used when /compare has fewer than two). */
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { MAX_COMPARE } from "@/lib/compare";
import { useCompare } from "./CompareProvider";
import { Icon } from "@/components/ui/Icon";

export function ComparePicker({ options, preselected }: { options: Array<{ slug: string; label: string; meta: string }>; preselected: string[] }) {
  const router = useRouter();
  const tray = useCompare();
  const [picked, setPicked] = useState<string[]>(() => [...new Set([...preselected, ...tray.items.map((i) => i.slug)])].slice(0, MAX_COMPARE));
  const [q, setQ] = useState("");
  const list = useMemo(() => options.filter((o) => `${o.label} ${o.meta}`.toLowerCase().includes(q.toLowerCase())), [options, q]);
  const toggle = (slug: string) => setPicked((p) => (p.includes(slug) ? p.filter((s) => s !== slug) : p.length >= MAX_COMPARE ? p : [...p, slug]));
  return (
    <div className="plate p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-ink-2">
          Pick <span className="text-ink">2 to 4 rackets</span>. Selected: <span className="num font-semibold text-ink">{picked.length}</span>/{MAX_COMPARE}
        </p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={picked.length < 2}
          onClick={() => router.push(`/compare?rackets=${picked.join(",")}`)}
        >
          Compare in 3D <Icon name="arrowRight" size={16} />
        </button>
      </div>
      <label className="relative mt-4 block">
        <span className="sr-only">Filter rackets</span>
        <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-2" />
        <input className="field pl-10" placeholder="Filter by name or brand…" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      <ul className="mt-3 grid gap-1 sm:grid-cols-2">
        {list.map((o) => {
          const on = picked.includes(o.slug);
          const full = !on && picked.length >= MAX_COMPARE;
          return (
            <li key={o.slug}>
              <label className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-ink/5 ${full ? "opacity-45" : ""}`}>
                <input type="checkbox" className="h-4 w-4 accent-court" checked={on} disabled={full} onChange={() => toggle(o.slug)} />
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{o.label}</span>
                  <span className="block truncate text-xs text-ink-3">{o.meta}</span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
