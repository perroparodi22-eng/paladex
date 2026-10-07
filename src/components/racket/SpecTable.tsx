/**
 * Manufacturer specification, one decision per ruled row: the value, what it
 * means for the player, and a button that shows the part on the 3D model.
 * Semantic HTML (a <dl>), so every spec is crawlable.
 */
import type { Racket } from "@/domain/types";
import { BALANCE_INFO, HARDNESS_INFO, SHAPE_INFO, SURFACE_INFO, VERIFICATION_INFO, thicknessEffect, weightEffect } from "@/domain/vocab";
import { formatWeight } from "@/lib/format";
import { estimatedBalanceMm } from "@/lib/racket-geometry";
import type { ViewerAction } from "@/components/three/ViewerBridge";
import { ShowOnModel } from "./ShowOnModel";

interface Row {
  key: string;
  label: string;
  value: string;
  explain?: string;
  action?: ViewerAction;
}

export function SpecTable({ racket }: { racket: Racket }) {
  const s = racket.specs;
  const rows: Row[] = [
    { key: "brand", label: "Brand", value: racket.brand.name },
    { key: "model", label: "Model", value: racket.name },
    { key: "collection", label: "Collection", value: racket.collection ?? "—" },
    { key: "year", label: "Year", value: racket.year ? String(racket.year) : "—" },
    {
      key: "shape",
      label: "Shape",
      value: SHAPE_INFO[s.shape].label,
      explain: `${SHAPE_INFO[s.shape].meaning} ${SHAPE_INFO[s.shape].effect}`,
      action: { view: "front" },
    },
    { key: "weight", label: "Weight", value: formatWeight(s.weightMinG, s.weightMaxG), explain: weightEffect(s.weightMinG, s.weightMaxG) },
    {
      key: "balance",
      label: "Balance",
      value: s.balance ? `${BALANCE_INFO[s.balance].label}${s.balanceMm ? ` · ${s.balanceMm} mm` : ` · ≈ ${estimatedBalanceMm(s.balance)} mm (estimated)`}` : "Not published",
      explain: s.balance
        ? `Where the weight is concentrated. ${BALANCE_INFO[s.balance].effect} Higher balance generally favours power, lower balance usually improves maneuverability.`
        : undefined,
      action: { view: "edge", overlays: ["balance"] },
    },
    {
      key: "thickness",
      label: "Thickness",
      value: s.thicknessMm ? `${s.thicknessMm} mm` : "Not published",
      explain: thicknessEffect(s.thicknessMm),
      action: { view: "edge", overlays: ["dimensions"] },
    },
    { key: "frame", label: "Frame material", value: s.frameMaterial ?? "Not published", action: { view: "top", hotspot: "frame" } },
    { key: "face", label: "Face material", value: s.faceMaterial ?? "Not published", action: { view: "detail", hotspot: "face" } },
    {
      key: "core",
      label: "Core",
      value: s.coreMaterial ?? "Not published",
      explain: s.hardness ? HARDNESS_INFO[s.hardness].effect : undefined,
      action: { view: "detail", hotspot: "core" },
    },
    {
      key: "surface",
      label: "Surface",
      value: s.surfaceFinish ? SURFACE_INFO[s.surfaceFinish].label : "Not published",
      explain: s.surfaceFinish ? SURFACE_INFO[s.surfaceFinish].effect : undefined,
      action: { view: "detail" },
    },
    { key: "hardness", label: "Hardness", value: s.hardness ? HARDNESS_INFO[s.hardness].label : "Not published", explain: s.hardness ? HARDNESS_INFO[s.hardness].meaning : undefined },
    {
      key: "sweet-spot",
      label: "Sweet spot",
      value: s.shape === "round" ? "Low and central" : s.shape === "diamond" ? "High on the face" : "Slightly above the middle",
      explain: "Derived from the shape class. The 3D zone is an illustration, not a measurement.",
      action: { view: "front", overlays: ["sweet-spot", "impact-zone"] },
    },
    { key: "grip", label: "Grip & handle", value: "Standard handle with overgrip", action: { view: "grip", hotspot: "grip" } },
  ];
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className={s.verification === "verified" ? "badge bg-ok/15 text-ok" : "badge badge-warn"}>{VERIFICATION_INFO[s.verification].label}</span>
        <span className="text-xs text-ink-3">
          {s.sourceNote ?? VERIFICATION_INFO[s.verification].description}
          {s.sourceUrl && (
            <>
              {" "}
              <a href={s.sourceUrl} target="_blank" rel="noopener noreferrer nofollow" className="underline hover:text-ink">
                Official product page
              </a>
            </>
          )}
        </span>
      </div>
      <dl className="border-t border-ink/10">
        {rows.map((r) => (
          <div key={r.key} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-4 gap-y-1 border-b border-ink/10 py-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto]">
            <dt className="text-sm text-ink-2">{r.label}</dt>
            <dd className="min-w-0">
              <span className="num font-semibold text-ink">{r.value}</span>
              {r.explain && <span className="mt-1 block text-[0.8125rem] leading-relaxed text-ink-2">{r.explain}</span>}
            </dd>
            {r.action && racket.model && racket.model.status !== "unavailable" ? (
              <dd className="col-start-2 sm:col-start-3 sm:row-start-1">
                <ShowOnModel action={r.action} specKey={r.key} className="-ml-2 sm:ml-0" />
              </dd>
            ) : (
              <dd className="hidden sm:block" />
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}
