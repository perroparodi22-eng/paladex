/**
 * "Where do you win your points?" A top-down padel court drawn in white lines
 * on graphite, tilted in perspective. Each zone links to a playing-style
 * collection: net (aggressive), transition (all-round), back glass (defensive).
 */
import Link from "next/link";

const ZONES = [
  { href: "/collections/aggressive", label: "At the net", sub: "Aggressive, finish overhead", y: 0, h: 34 },
  { href: "/collections/all-round", label: "Transition", sub: "All-round, attack and defend", y: 34, h: 29 },
  { href: "/collections/defensive", label: "Back glass", sub: "Defensive, control and lobs", y: 63, h: 37 },
];

export function CourtZones() {
  return (
    <div className="[perspective:1400px]">
      <div className="relative mx-auto aspect-[10/12] w-full max-w-[420px] overflow-hidden rounded-[26px] border border-white/10 bg-[radial-gradient(80%_60%_at_50%_30%,#1b1e24,#0d0e11)] shadow-lift transition-transform duration-700 [transform:rotateX(14deg)] [transition-timing-function:var(--ease-out-expo)] hover:[transform:rotateX(4deg)]">
        <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-2 bg-[repeating-linear-gradient(90deg,rgb(255_255_255/0.6)_0_2px,transparent_2px_9px)]" />
        <span aria-hidden className="pointer-events-none absolute inset-x-0 top-[63%] h-[2px] bg-white/55" />
        <span aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-[63%] w-[2px] -translate-x-1/2 bg-white/55" />
        {ZONES.map((z) => (
          <Link
            key={z.href}
            href={z.href}
            className="group absolute inset-x-0 flex flex-col items-center justify-center px-6 text-center transition-colors duration-300 hover:bg-white/[0.05] focus-visible:bg-white/[0.05]"
            style={{ top: `${z.y}%`, height: `${z.h}%` }}
          >
            <span className="display rounded-xl bg-[#121418] px-3 py-1 text-[clamp(1.5rem,2.6vw,1.9rem)]">{z.label}</span>
            <span className="rounded-full bg-[#121418] px-3 text-sm text-ink-2">{z.sub}</span>
            <span className="mt-2 inline-flex translate-y-1 items-center gap-1 rounded-full bg-court px-3 py-1 text-xs font-semibold text-on-court opacity-0 transition-[opacity,transform] duration-300 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100">
              See the rackets
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
