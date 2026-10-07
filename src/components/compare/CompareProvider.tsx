"use client";
/**
 * Compare selection (up to 4 rackets), kept in this browser only.
 * No account needed; nothing leaves the device.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { MAX_COMPARE } from "@/lib/compare";
import { track } from "@/lib/analytics";

export interface CompareItem {
  slug: string;
  name: string;
  brand: string;
}

interface CompareValue {
  items: CompareItem[];
  has: (slug: string) => boolean;
  toggle: (item: CompareItem) => "added" | "removed" | "full";
  remove: (slug: string) => void;
  clear: () => void;
  full: boolean;
}

const KEY = "paladex:compare";
const Ctx = createContext<CompareValue | null>(null);

export function CompareProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<CompareItem[]>([]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as CompareItem[];
        if (Array.isArray(parsed)) setItems(parsed.filter((i) => typeof i?.slug === "string").slice(0, MAX_COMPARE));
      }
    } catch {
      // ignore
    }
  }, []);

  const persist = (next: CompareItem[]) => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  };

  const toggle = useCallback(
    (item: CompareItem): "added" | "removed" | "full" => {
      if (items.some((i) => i.slug === item.slug)) {
        const next = items.filter((i) => i.slug !== item.slug);
        setItems(next);
        persist(next);
        return "removed";
      }
      if (items.length >= MAX_COMPARE) return "full";
      const next = [...items, item];
      if (next.length === 2) track("comparison_started", { slugs: next.map((i) => i.slug).join(",") });
      setItems(next);
      persist(next);
      return "added";
    },
    [items],
  );

  const remove = useCallback((slug: string) => {
    setItems((cur) => {
      const next = cur.filter((i) => i.slug !== slug);
      persist(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setItems([]);
    persist([]);
  }, []);

  const value = useMemo<CompareValue>(
    () => ({ items, has: (s) => items.some((i) => i.slug === s), toggle, remove, clear, full: items.length >= MAX_COMPARE }),
    [items, toggle, remove, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCompare(): CompareValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCompare must be used inside CompareProvider");
  return v;
}
