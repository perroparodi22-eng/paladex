import type { Money } from "@/domain/types";

const priceFormatters = new Map<string, Intl.NumberFormat>();

export function formatPrice(m: Money | null | undefined, opts: { compact?: boolean } = {}): string {
  if (!m) return "—";
  const key = `${m.currency}|${opts.compact ? 1 : 0}`;
  let f = priceFormatters.get(key);
  if (!f) {
    f = new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency: m.currency,
      minimumFractionDigits: opts.compact ? 0 : 2,
      maximumFractionDigits: opts.compact ? 0 : 2,
    });
    priceFormatters.set(key, f);
  }
  return f.format(opts.compact ? Math.round(m.amountCents / 100) : m.amountCents / 100);
}

export function formatWeight(min: number | null, max: number | null): string {
  if (min && max) return min === max ? `${min} g` : `${min}–${max} g`;
  if (min ?? max) return `${min ?? max} g`;
  return "—";
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
}

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
