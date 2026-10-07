"use client";
import { useState } from "react";
import { useCompare, type CompareItem } from "./CompareProvider";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export function CompareToggle({ item, className, size = "sm" }: { item: CompareItem; className?: string; size?: "sm" | "md" }) {
  const { has, toggle, full } = useCompare();
  const [msg, setMsg] = useState<string | null>(null);
  const selected = has(item.slug);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => {
          const r = toggle(item);
          setMsg(r === "full" ? "Compare holds up to 4 rackets" : null);
          if (r === "full") setTimeout(() => setMsg(null), 2600);
        }}
        className={cn("btn", size === "sm" ? "btn-sm" : "", selected ? "bg-court-tint text-court-deep hover:bg-court-tint" : "btn-ghost", className)}
        title={selected ? "Remove from comparison" : full ? "Compare is full (4 rackets)" : "Add to comparison"}
      >
        <Icon name={selected ? "check" : "compare"} size={16} />
        {selected ? "Comparing" : "Compare"}
      </button>
      {msg && (
        <span role="status" className="absolute bottom-full left-0 mb-2 whitespace-nowrap rounded-full bg-ink px-3 py-1 text-xs font-medium text-white shadow-lift">
          {msg}
        </span>
      )}
    </span>
  );
}
