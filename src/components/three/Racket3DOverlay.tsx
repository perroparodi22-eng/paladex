"use client";
/**
 * Labels for the active 3D overlays (pinned through data-anchor) and a
 * legend that states what each overlay is based on.
 */
import type { OverlayConfig, OverlayKind } from "@/domain/types";
import { BASIS_INFO, OVERLAY_INFO } from "@/domain/vocab";

function Tag({ anchor, children, tone = "line" }: { anchor: string; children: React.ReactNode; tone?: "line" | "ball" | "serve" }) {
  const color = tone === "ball" ? "bg-ball text-ball-deep" : tone === "serve" ? "bg-court text-on-court" : "bg-surface-2 text-ink";
  return (
    <div data-anchor={anchor} className="anchor pointer-events-none">
      <span className={`num inline-block -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full px-2.5 py-1 text-[0.75rem] font-bold shadow-[0_6px_16px_-8px_rgb(17_22_58/0.7)] ${color}`}>
        {children}
      </span>
    </div>
  );
}

export function Racket3DOverlayLabels({ overlays, active }: { overlays: OverlayConfig[]; active: OverlayKind[] }) {
  const get = (k: OverlayKind) => (active.includes(k) ? overlays.find((o) => o.kind === k) : undefined);
  const sweet = get("sweet-spot");
  const impact = get("impact-zone");
  const balance = get("balance");
  const dims = get("dimensions");
  const weight = get("weight-distribution");
  return (
    <>
      {sweet && (
        <Tag anchor="ov:sweet-spot" tone="ball">
          Sweet spot
        </Tag>
      )}
      {impact && (
        <Tag anchor="ov:impact-zone" tone="serve">
          Impact zone
        </Tag>
      )}
      {balance && (
        <Tag anchor="ov:balance" tone="serve">
          {balance.params.estimated ? "≈ " : ""}
          {String(balance.params.mm)} mm
        </Tag>
      )}
      {dims && (
        <>
          <Tag anchor="ov:dim-length">{String(dims.params.lengthMm)} mm</Tag>
          <Tag anchor="ov:dim-width">{String(dims.params.widthMm)} mm</Tag>
          <Tag anchor="ov:dim-thickness" tone="ball">
            {String(dims.params.thicknessMm)} mm
          </Tag>
        </>
      )}
      {weight && <Tag anchor="ov:weight">Mass</Tag>}
    </>
  );
}

export function Racket3DOverlayLegend({ overlays, active }: { overlays: OverlayConfig[]; active: OverlayKind[] }) {
  const shown = overlays.filter((o) => active.includes(o.kind));
  if (!shown.length) return null;
  return (
    <div className="pointer-events-none hidden max-w-[300px] sm:block">
      <ul className="plate space-y-2 p-3.5">
        {shown.map((o) => (
          <li key={o.kind} className="text-xs leading-snug">
            <span className="font-semibold text-ink">{OVERLAY_INFO[o.kind].label}</span>
            <span className="text-ink-3"> · {BASIS_INFO[o.basis].label}</span>
            {o.note && <span className="mt-0.5 block text-ink-2">{o.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
