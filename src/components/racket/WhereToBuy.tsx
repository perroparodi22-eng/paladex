/**
 * Retailer offers. Every Buy button goes through /go/[offerId], which logs
 * the click and redirects only to allow-listed retailer domains. Demo prices
 * and placeholder affiliate links are labelled as such: nothing pretends to
 * be a live offer.
 */
import Link from "next/link";
import type { Offer, Racket } from "@/domain/types";
import { STOCK_INFO } from "@/domain/vocab";
import { formatDate, formatPrice } from "@/lib/format";
import { Icon } from "@/components/ui/Icon";
import { siteConfig } from "@/config/site";
import { cn } from "@/lib/cn";

function BuyButton({ offer, primary }: { offer: Offer; primary?: boolean }) {
  const disabled = !offer.available;
  return (
    <a
      href={`/go/${offer.id}`}
      target="_blank"
      rel="sponsored nofollow noopener noreferrer"
      aria-disabled={disabled || undefined}
      className={cn("btn btn-sm min-w-24", primary ? "btn-primary" : "btn-secondary", disabled && "pointer-events-none opacity-45")}
      aria-label={`Buy at ${offer.retailer.name} for ${formatPrice(offer.price)}${offer.linkIsPlaceholder ? " (link not active yet)" : ""}`}
    >
      {disabled ? "Sold out" : "Buy"} <Icon name="external" size={14} />
    </a>
  );
}

export function WhereToBuy({ racket }: { racket: Racket }) {
  const offers = racket.offers;
  const best = offers.find((o) => o.available) ?? null;
  const anyDemo = offers.some((o) => o.isDemo || o.linkIsPlaceholder);
  if (!offers.length) {
    return (
      <div className="plate p-5">
        <p className="font-semibold">No retailers listed yet</p>
        <p className="mt-1 text-sm text-ink-2">We haven&apos;t added retailers for this racket. Check back soon.</p>
      </div>
    );
  }
  return (
    <div>
      {best && (
        <div className="plate flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <p className="label">Best current price</p>
            <p className="num mt-1 text-4xl font-bold leading-none">{formatPrice(best.price)}</p>
            <p className="mt-1.5 text-sm text-ink-2">
              at <span className="text-ink">{best.retailer.name}</span>
              {best.isDemo && <span className="badge badge-warn ml-2">Sample price</span>}
            </p>
          </div>
          <BuyButton offer={best} primary />
        </div>
      )}
      <ul className="mt-3 divide-y divide-ink/8 border-y border-ink/8">
        {offers.map((o) => (
          <li key={o.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 py-3">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 font-semibold">
                {o.retailer.name}
                {o.isDemo && <span className="badge !text-[0.625rem]">Demo retailer</span>}
                {o.linkIsPlaceholder && <span className="badge badge-warn !text-[0.625rem]">Link not active</span>}
              </p>
              <p className="truncate text-xs text-ink-3">
                {STOCK_INFO[o.stockStatus]}
                {o.shippingInfo ? ` · ${o.shippingInfo}` : ""} · checked {formatDate(o.lastCheckedAt)}
              </p>
            </div>
            <p className="num text-right font-bold">{formatPrice(o.price)}</p>
            <BuyButton offer={o} />
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs leading-relaxed text-ink-3">
        {anyDemo && "Prices and retailers shown here are sample data. Affiliate links are not active yet. "}
        {siteConfig.name} may earn a commission when you buy through these links. It doesn&apos;t change your price or our evaluations.{" "}
        <Link href="/legal/affiliate-disclosure" className="underline hover:text-ink">
          Affiliate disclosure
        </Link>
      </p>
    </div>
  );
}
