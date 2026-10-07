"use client";
/**
 * Brand tiles: each brand shown by its logo in the studio. On the rackets page
 * a tile filters the list in place; elsewhere it links to the rackets page
 * with that brand selected.
 *
 * The rail scrolls sideways by touch, trackpad, arrow buttons (mouse users) or
 * by dragging with the mouse.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export interface BrandTile {
  slug: string;
  name: string;
  count: number;
  logoUrl: string | null;
}

function TileBody({ brand, active }: { brand: BrandTile; active: boolean }) {
  return (
    <>
      <span className="card-sky relative grid h-36 place-items-center overflow-hidden rounded-[16px] [perspective:700px] sm:h-40">
        <span className="grid h-full w-full place-items-center px-3 transition-transform duration-700 [transition-timing-function:var(--ease-out-expo)] group-hover:[transform:rotateY(-12deg)_scale(1.06)]">
          {brand.logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- small static logo, already sized
            <img src={brand.logoUrl} alt={`${brand.name} logo`} draggable={false} className="max-h-[44%] max-w-[86%] object-contain drop-shadow-[0_10px_18px_rgb(0_0_0/0.55)]" loading="lazy" />
          ) : (
            <span className="display text-center text-[1.6rem] leading-none text-ink">{brand.name}</span>
          )}
        </span>
      </span>
      <span className="mt-3 flex items-baseline justify-between gap-2 px-1">
        <span className={cn("title text-[1.05rem]", active ? "text-on-court" : "text-ink")}>{brand.name}</span>
        <span className={cn("num text-xs", active ? "text-on-court/70" : "text-ink-3")}>{brand.count}</span>
      </span>
    </>
  );
}

const tileClass = (active: boolean) =>
  cn(
    "group block w-[9.5rem] shrink-0 snap-start rounded-[20px] border p-2 pb-3 text-left transition-[background-color,border-color,transform] duration-300 sm:w-[11rem]",
    active ? "border-court bg-court" : "border-white/8 bg-surface hover:-translate-y-0.5 hover:border-white/20",
  );

export function BrandTiles({
  brands,
  active,
  onSelect,
  allCount,
}: {
  brands: BrandTile[];
  active?: string | null;
  /** When set, tiles filter in place instead of linking. */
  onSelect?: (slug: string | null) => void;
  allCount?: number;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: true, end: false });

  const measure = useCallback(() => {
    const el = rail.current;
    if (!el) return;
    setEdges({ start: el.scrollLeft <= 4, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 4 });
  }, []);

  useEffect(() => {
    const el = rail.current;
    if (!el) return;
    measure();
    el.addEventListener("scroll", measure, { passive: true });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", measure);
      ro.disconnect();
    };
  }, [measure, brands.length]);

  // Keep the chosen brand in sight, e.g. when arriving from /rackets?brand=nox on a phone.
  useEffect(() => {
    const el = rail.current;
    const tile = el?.querySelector<HTMLElement>('[aria-checked="true"]');
    if (!el || !tile) return;
    const left = tile.offsetLeft - parseFloat(getComputedStyle(el).paddingLeft);
    if (tile.offsetLeft < el.scrollLeft || tile.offsetLeft + tile.offsetWidth > el.scrollLeft + el.clientWidth) {
      el.scrollTo({ left, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [active]);

  const page = (dir: 1 | -1) => {
    const el = rail.current;
    if (!el) return;
    el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };

  // Mouse drag to scroll. A drag that moved the rail does not count as a click on a tile.
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null);
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse" || e.button !== 0 || !rail.current) return;
    drag.current = { x: e.clientX, left: rail.current.scrollLeft, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    const el = rail.current;
    if (!d || !el) return;
    const dx = e.clientX - d.x;
    if (!d.moved && Math.abs(dx) < 6) return;
    if (!d.moved) {
      d.moved = true;
      el.setPointerCapture(e.pointerId);
      el.style.scrollSnapType = "none";
    }
    el.scrollLeft = d.left - dx;
  };
  const endDrag = () => {
    const el = rail.current;
    if (el) el.style.scrollSnapType = "";
    // Clear after the click event that follows pointerup.
    window.setTimeout(() => (drag.current = null), 0);
  };
  const onClickCapture = (e: React.MouseEvent) => {
    if (drag.current?.moved) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const arrow = "absolute top-[4.5rem] z-10 hidden h-11 w-11 place-items-center rounded-full border border-white/12 bg-[#111317]/95 text-ink shadow-lift transition-[opacity,transform] duration-300 hover:scale-105 [@media(hover:hover)_and_(pointer:fine)]:grid sm:top-[5rem]";

  return (
    <div className="relative">
      <button type="button" aria-label="Scroll brands left" onClick={() => page(-1)} className={cn(arrow, "-left-2 sm:-left-3", edges.start && "pointer-events-none opacity-0")} tabIndex={edges.start ? -1 : 0}>
        <Icon name="chevronLeft" size={20} />
      </button>
      <div
        ref={rail}
        className="no-scrollbar relative -mx-4 flex snap-x scroll-pl-4 gap-3 overflow-x-auto px-4 pb-2 select-none sm:-mx-6 sm:scroll-pl-6 sm:px-6 lg:-mx-10 lg:scroll-pl-10 lg:px-10"
        role={onSelect ? "radiogroup" : undefined}
        aria-label="Brands"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onClickCapture={onClickCapture}
      >
        {onSelect && (
          <button type="button" role="radio" aria-checked={!active} onClick={() => onSelect(null)} className={cn(tileClass(!active), "flex flex-col")}>
            <span className="card-sky grid h-36 place-items-center rounded-[16px] sm:h-40">
              <span className={cn("display text-3xl", !active ? "text-ink" : "text-ink-2")}>All</span>
            </span>
            <span className="mt-3 flex items-baseline justify-between gap-2 px-1">
              <span className={cn("title text-[1.05rem]", !active ? "text-on-court" : "text-ink")}>All brands</span>
              {allCount !== undefined && <span className={cn("num text-xs", !active ? "text-on-court/70" : "text-ink-3")}>{allCount}</span>}
            </span>
          </button>
        )}
        {brands.map((b) =>
          onSelect ? (
            <button key={b.slug} type="button" role="radio" aria-checked={active === b.slug} onClick={() => onSelect(active === b.slug ? null : b.slug)} className={tileClass(active === b.slug)}>
              <TileBody brand={b} active={active === b.slug} />
            </button>
          ) : (
            <Link key={b.slug} href={`/rackets?brand=${b.slug}`} className={tileClass(false)} draggable={false}>
              <TileBody brand={b} active={false} />
            </Link>
          ),
        )}
      </div>
      <button type="button" aria-label="Scroll brands right" onClick={() => page(1)} className={cn(arrow, "-right-2 sm:-right-3", edges.end && "pointer-events-none opacity-0")} tabIndex={edges.end ? -1 : 0}>
        <Icon name="chevronRight" size={20} />
      </button>
    </div>
  );
}
