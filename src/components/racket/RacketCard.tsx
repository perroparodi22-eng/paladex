/**
 * Catalog card. The racket stands in a small black studio (live 3D on hover,
 * quick view on tap) and leans toward you on hover; below, the few facts that
 * decide a purchase. The whole card opens the racket.
 */
import Link from "next/link";
import type { RacketSummary } from "@/domain/types";
import { BALANCE_INFO, SHAPE_INFO } from "@/domain/vocab";
import { formatPrice, formatWeight } from "@/lib/format";
import { Racket3DPreview } from "@/components/three/Racket3DPreview";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export function RacketCard({ racket, priority = false, className }: { racket: RacketSummary; priority?: boolean; className?: string }) {
  const r = racket;
  const price = r.priceFrom ?? r.indicativePrice;
  const facts = [SHAPE_INFO[r.shape].label, formatWeight(r.weightMinG, r.weightMaxG), r.balance ? `${BALANCE_INFO[r.balance].label.split(" (")[0]} balance` : null].filter(Boolean);
  return (
    <article
      data-preview-host
      className={cn(
        "group/card relative flex flex-col rounded-card border border-white/7 bg-surface p-2 transition-[border-color,transform,box-shadow] duration-500 [transition-timing-function:var(--ease-out-expo)] hover:-translate-y-1 hover:border-white/16 hover:shadow-lift",
        className,
      )}
    >
      <div className="card-sky relative aspect-[4/5] overflow-hidden rounded-[16px] [perspective:1000px]">
        <div className="absolute inset-0 transition-transform duration-700 [transition-timing-function:var(--ease-out-expo)] [transform-style:preserve-3d] group-hover/card:[transform:rotateY(-10deg)_rotateX(3deg)_scale(1.04)]">
          <Racket3DPreview racket={r} className="absolute inset-0" priority={priority} />
        </div>
        <span aria-hidden className="pointer-events-none absolute inset-x-[22%] bottom-[3%] h-10 bg-[radial-gradient(closest-side,rgb(0_0_0/0.75),transparent)]" />
        <div className="pointer-events-none absolute left-2.5 top-2.5 z-30 flex flex-wrap gap-1.5">
          <ProvenanceBadge status={r.modelStatus} />
        </div>
        {r.isNew && <span className="badge badge-court pointer-events-none absolute right-2.5 top-2.5 z-30">New</span>}
      </div>
      <div className="flex flex-1 flex-col px-2.5 pb-2 pt-4">
        <p className="label">
          {r.brand.name}
          {r.year ? <span className="text-ink-3"> · {r.year}</span> : null}
        </p>
        <h3 className="title mt-0.5 text-[1.3rem]">
          <Link href={`/rackets/${r.slug}`} className="after:absolute after:inset-0 after:z-10 after:rounded-card focus-visible:outline-none">
            {r.name}
          </Link>
        </h3>
        <p className="mt-1.5 text-[0.8125rem] text-ink-2">{facts.join(", ")}</p>
        {(r.proPlayers?.length ?? 0) > 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-[0.8125rem] text-ink">
            <Icon name="trophy" size={14} className="shrink-0 text-ball" />
            {r.proPlayers.map((p) => p.name).join(" · ")}
          </p>
        )}
        <div className="mt-auto flex items-end justify-between gap-3 pt-5">
          <div>
            <p className="label !text-[0.75rem]">{r.priceFrom ? "From" : price ? "Indicative" : "Price"}</p>
            <p className={price ? "num text-[1.25rem] font-semibold leading-tight" : "text-[0.95rem] font-medium leading-tight text-ink-2"}>
              {price ? formatPrice(price, { compact: true }) : "Not listed"}
            </p>
          </div>
          <span className="flex items-center gap-2 text-sm text-ink-2">
            {r.scores && (
              <span className="num" title="Platform score (sample evaluation)">
                {r.scores.overall.toFixed(1)}
                <span className="text-ink-3">/10</span>
              </span>
            )}
            <span className="grid h-9 w-9 place-items-center rounded-full border border-white/12 text-ink transition-colors group-hover/card:border-court group-hover/card:bg-court group-hover/card:text-on-court">
              <Icon name="arrowRight" size={16} />
            </span>
          </span>
        </div>
      </div>
    </article>
  );
}
