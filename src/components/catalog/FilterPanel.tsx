"use client";
/**
 * Catalog filters. The same panel renders as a sidebar on desktop and inside a
 * bottom sheet on phones. Counts show how many rackets carry each option.
 */
import type { Balance, Hardness, PlayerLevel, PlayingStyle, RacketShape } from "@/domain/types";
import { BALANCES, HARDNESSES, PLAYER_LEVELS, PLAYING_STYLES, RACKET_SHAPES } from "@/domain/types";
import { BALANCE_INFO, HARDNESS_INFO, LEVEL_INFO, SHAPE_INFO, STYLE_INFO } from "@/domain/vocab";
import type { CatalogFilters } from "@/lib/catalog/filters";
import { cn } from "@/lib/cn";

type Counts = {
  brands: Map<string, number>;
  shapes: Map<string, number>;
  levels: Map<string, number>;
  styles: Map<string, number>;
  balances: Map<string, number>;
  hardness: Map<string, number>;
};

function Group({ title, children, hint }: { title: string; children: React.ReactNode; hint?: string }) {
  return (
    <fieldset className="border-b border-ink/8 py-4 first:pt-0">
      <legend className="label mb-2.5 text-ink">{title}</legend>
      {hint && <p className="-mt-1 mb-2 text-xs text-ink-3">{hint}</p>}
      {children}
    </fieldset>
  );
}

function toggle<T extends string>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function ChipSet<T extends string>({
  values,
  selected,
  label,
  count,
  onChange,
}: {
  values: readonly T[];
  selected: T[];
  label: (v: T) => string;
  count?: (v: T) => number | undefined;
  onChange: (next: T[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => {
        const n = count?.(v);
        return (
          <button
            key={v}
            type="button"
            // No matches: readable grey with a dashed outline (fading the chip failed contrast).
            className={cn("chip min-h-9", n === 0 && !selected.includes(v) && "border-dashed text-ink-3")}
            aria-pressed={selected.includes(v)}
            onClick={() => onChange(toggle(selected, v))}
          >
            {label(v)}
            {n !== undefined && <span className="num text-[0.6875rem] text-current">{n}</span>}
          </button>
        );
      })}
    </div>
  );
}

function ScoreMin({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number | null) => void }) {
  const id = `min-${label}`;
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
      <label htmlFor={id} className="text-sm text-ink-2">
        {label} at least
      </label>
      <span className="num text-sm text-ink">{value === null ? "Any" : value.toFixed(1)}</span>
      <input
        id={id}
        type="range"
        min={0}
        max={10}
        step={0.5}
        value={value ?? 0}
        onChange={(e) => onChange(Number(e.target.value) === 0 ? null : Number(e.target.value))}
        className="col-span-2 w-full"
      />
    </div>
  );
}

export function FilterPanel({
  filters,
  counts,
  brands,
  years,
  onChange,
  hideBrands = false,
}: {
  filters: CatalogFilters;
  counts: Counts;
  brands: Array<{ slug: string; name: string }>;
  years: number[];
  onChange: (patch: Partial<CatalogFilters>, key: string) => void;
  /** Brands are chosen from the brand tiles instead. */
  hideBrands?: boolean;
}) {
  return (
    <div>
      {!hideBrands && <Group title="Brand">
        <ChipSet
          values={brands.map((b) => b.slug)}
          selected={filters.brands}
          label={(s) => brands.find((b) => b.slug === s)?.name ?? s}
          count={(s) => counts.brands.get(s) ?? 0}
          onChange={(v) => onChange({ brands: v }, "brand")}
        />
      </Group>}
      <Group title="Shape" hint="Round means control, diamond means power">
        <ChipSet<RacketShape> values={RACKET_SHAPES} selected={filters.shapes} label={(s) => SHAPE_INFO[s].label} count={(s) => counts.shapes.get(s) ?? 0} onChange={(v) => onChange({ shapes: v }, "shape")} />
      </Group>
      <Group title="Player level">
        <ChipSet<PlayerLevel> values={PLAYER_LEVELS} selected={filters.levels} label={(s) => LEVEL_INFO[s].label} count={(s) => counts.levels.get(s) ?? 0} onChange={(v) => onChange({ levels: v }, "level")} />
      </Group>
      <Group title="Playing style">
        <ChipSet<PlayingStyle> values={PLAYING_STYLES} selected={filters.styles} label={(s) => STYLE_INFO[s].label} count={(s) => counts.styles.get(s) ?? 0} onChange={(v) => onChange({ styles: v }, "style")} />
      </Group>
      <Group title="Balance" hint="Higher = more head weight for overheads">
        <ChipSet<Balance> values={BALANCES} selected={filters.balances} label={(s) => BALANCE_INFO[s].label.split(" (")[0]} count={(s) => counts.balances.get(s) ?? 0} onChange={(v) => onChange({ balances: v }, "balance")} />
      </Group>
      <Group title="Core feel" hint="Softer = comfort · Harder = precision at speed">
        <ChipSet<Hardness> values={HARDNESSES} selected={filters.hardness} label={(s) => HARDNESS_INFO[s].label} count={(s) => counts.hardness.get(s) ?? 0} onChange={(v) => onChange({ hardness: v }, "hardness")} />
      </Group>
      <Group title="Price (€)">
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-ink-3">
            Min
            <input
              type="number"
              inputMode="numeric"
              min={0}
              className="field mt-1"
              placeholder="0"
              value={filters.priceMin ?? ""}
              onChange={(e) => onChange({ priceMin: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) }, "price")}
            />
          </label>
          <label className="text-xs text-ink-3">
            Max
            <input
              type="number"
              inputMode="numeric"
              min={0}
              className="field mt-1"
              placeholder="Any"
              value={filters.priceMax ?? ""}
              onChange={(e) => onChange({ priceMax: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) }, "price")}
            />
          </label>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            [null, 100],
            [100, 200],
            [200, 300],
            [300, null],
          ].map(([a, b]) => (
            <button
              key={`${a}-${b}`}
              type="button"
              className="chip min-h-9"
              aria-pressed={filters.priceMin === a && filters.priceMax === b}
              onClick={() => onChange({ priceMin: a, priceMax: b }, "price")}
            >
              {a === null ? `Under €${b}` : b === null ? `€${a}+` : `€${a}–${b}`}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Weight">
        <div className="flex flex-wrap gap-1.5">
          {[
            ["Light (≤ 355 g)", null, 355],
            ["Medium (355–368 g)", 355, 368],
            ["Heavy (368 g +)", 368, null],
          ].map(([label, a, b]) => (
            <button
              key={String(label)}
              type="button"
              className="chip min-h-9"
              aria-pressed={filters.weightMin === a && filters.weightMax === b}
              onClick={() =>
                filters.weightMin === a && filters.weightMax === b
                  ? onChange({ weightMin: null, weightMax: null }, "weight")
                  : onChange({ weightMin: a as number | null, weightMax: b as number | null }, "weight")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Year">
        <select
          className="field"
          value={filters.yearMin ?? ""}
          onChange={(e) => onChange({ yearMin: e.target.value ? Number(e.target.value) : null }, "year")}
          aria-label="Model year from"
        >
          <option value="">Any year</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y} or newer
            </option>
          ))}
        </select>
      </Group>
      <Group title="Platform scores" hint="Our evaluation, 1–10">
        <div className="space-y-3">
          <ScoreMin label="Power" value={filters.minPower} onChange={(v) => onChange({ minPower: v }, "power")} />
          <ScoreMin label="Control" value={filters.minControl} onChange={(v) => onChange({ minControl: v }, "control")} />
          <ScoreMin label="Maneuverability" value={filters.minManeuverability} onChange={(v) => onChange({ minManeuverability: v }, "maneuverability")} />
        </div>
      </Group>
      <Group title="3D model">
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="3D model availability">
          {(
            [
              ["any", "Any"],
              ["interactive", "Interactive 3D"],
              ["platform", "Real-design 3D"],
              ["none", "3D coming soon"],
            ] as const
          ).map(([v, label]) => (
            <button key={v} type="button" role="radio" aria-checked={filters.model === v} className="chip min-h-9" data-active={filters.model === v} onClick={() => onChange({ model: v }, "model")}>
              {label}
            </button>
          ))}
        </div>
      </Group>
    </div>
  );
}
