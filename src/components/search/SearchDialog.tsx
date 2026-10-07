"use client";
/**
 * Site search (⌘K / Ctrl+K / "/"). Searches rackets, brands, collections and
 * guides on the client from a small index fetched once. Only the query
 * length and result count are tracked, never the query text.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

export interface SearchIndex {
  rackets: Array<{ slug: string; name: string; brand: string; meta: string; terms: string }>;
  brands: Array<{ slug: string; name: string; count: number }>;
  collections: Array<{ slug: string; title: string }>;
  guides: Array<{ slug: string; title: string }>;
}

let indexPromise: Promise<SearchIndex> | null = null;
function loadIndex() {
  indexPromise ??= fetch("/api/search-index").then((r) => {
    if (!r.ok) throw new Error("search index unavailable");
    return r.json() as Promise<SearchIndex>;
  });
  indexPromise.catch(() => (indexPromise = null));
  return indexPromise;
}

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");

interface Result {
  href: string;
  title: string;
  meta: string;
  group: "Rackets" | "Brands" | "Collections" | "Guides";
}

function search(index: SearchIndex, q: string): Result[] {
  const tokens = norm(q).split(/\s+/).filter(Boolean);
  if (!tokens.length) return [];
  const hit = (text: string) => tokens.every((t) => norm(text).includes(t));
  const out: Result[] = [];
  for (const r of index.rackets) if (hit(`${r.brand} ${r.name} ${r.terms}`)) out.push({ href: `/rackets/${r.slug}`, title: `${r.brand} ${r.name}`, meta: r.meta, group: "Rackets" });
  for (const b of index.brands) if (hit(b.name)) out.push({ href: `/brands/${b.slug}`, title: b.name, meta: `${b.count} rackets`, group: "Brands" });
  for (const c of index.collections) if (hit(c.title)) out.push({ href: `/collections/${c.slug}`, title: c.title, meta: "Collection", group: "Collections" });
  for (const g of index.guides) if (hit(g.title)) out.push({ href: `/guides/${g.slug}`, title: g.title, meta: "Guide", group: "Guides" });
  return out.slice(0, 24);
}

export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [index, setIndex] = useState<SearchIndex | null>(null);
  const [error, setError] = useState(false);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setCursor(0);
    loadIndex()
      .then(setIndex)
      .catch(() => setError(true));
    const t = setTimeout(() => input.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [open]);

  const results = useMemo(() => (index ? search(index, q) : []), [index, q]);

  useEffect(() => {
    if (!q) return;
    const t = setTimeout(() => track("search_performed", { length: q.length, results: results.length }), 700);
    return () => clearTimeout(t);
  }, [q, results.length]);

  const go = (href: string) => {
    onClose();
    router.push(href);
  };

  let lastGroup = "";
  return (
    <Dialog open={open} onClose={onClose} title="Search" variant="center" hideTitle className="sm:top-[12vh] sm:mt-0 sm:mb-auto">
      <div className="flex items-center gap-3 border-b border-ink/10 px-4">
        <Icon name="search" className="text-ink-2" />
        <input
          ref={input}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setCursor(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(c + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            } else if (e.key === "Enter") {
              if (results[cursor]) go(results[cursor].href);
              else if (q.trim()) go(`/rackets?q=${encodeURIComponent(q.trim())}`);
            }
          }}
          placeholder="Search rackets, brands or models…"
          aria-label="Search rackets, brands or models"
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls="search-results"
          aria-activedescendant={results[cursor] ? `sr-${cursor}` : undefined}
          className="h-14 flex-1 bg-transparent text-lg outline-none placeholder:text-ink-3"
        />
        <kbd className="label hidden rounded-xl border border-ink/15 px-1.5 py-0.5 sm:inline">Esc</kbd>
      </div>
      <div id="search-results" role="listbox" aria-label="Search results" className="max-h-[60dvh] overflow-y-auto p-2">
        {error && <p className="p-4 text-sm text-ink-2">Search is unavailable right now. Try the racket database instead.</p>}
        {!q && !error && (
          <div className="p-3">
            <p className="label mb-2">Try</p>
            <div className="flex flex-wrap gap-2">
              {["diamond", "beginner", "Nox", "control", "soft"].map((s) => (
                <button key={s} type="button" className="chip" onClick={() => setQ(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {q && index && results.length === 0 && (
          <div className="p-4 text-sm text-ink-2">
            No matches for <span className="text-ink">“{q}”</span>.{" "}
            <Link href="/rackets" onClick={onClose} className="text-court underline">
              Browse all rackets
            </Link>
          </div>
        )}
        {results.map((r, i) => {
          const header = r.group !== lastGroup ? r.group : null;
          lastGroup = r.group;
          return (
            <div key={r.href}>
              {header && <p className="label px-3 pb-1 pt-3">{header}</p>}
              <button
                id={`sr-${i}`}
                role="option"
                aria-selected={i === cursor}
                type="button"
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(r.href)}
                className={cn("flex w-full items-center justify-between gap-4 rounded-xl px-3 py-2.5 text-left", i === cursor && "bg-ink/7")}
              >
                <span className="font-semibold">{r.title}</span>
                <span className="truncate text-xs text-ink-2">{r.meta}</span>
              </button>
            </div>
          );
        })}
      </div>
    </Dialog>
  );
}
