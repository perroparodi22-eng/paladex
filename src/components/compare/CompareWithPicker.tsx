"use client";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";

/** "Compare with…" select on a racket page: jumps straight into a 3D comparison. */
export function CompareWithPicker({ slug, options }: { slug: string; options: Array<{ slug: string; label: string }> }) {
  const router = useRouter();
  return (
    <label className="relative block">
      <span className="sr-only">Compare with another racket</span>
      <Icon name="compare" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-2" />
      <select
        className="field h-11 appearance-none pl-9 pr-9 text-sm"
        defaultValue=""
        onChange={(e) => {
          if (!e.target.value) return;
          track("comparison_started", { slugs: `${slug},${e.target.value}`, source: "racket-page" });
          router.push(`/compare?rackets=${slug},${e.target.value}`);
        }}
      >
        <option value="">Compare in 3D with…</option>
        {options.map((o) => (
          <option key={o.slug} value={o.slug}>
            {o.label}
          </option>
        ))}
      </select>
      <Icon name="chevronDown" size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-2" />
    </label>
  );
}
