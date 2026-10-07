/**
 * Platform score on a 0–10 gauge. The fill swings in with a little overshoot
 * as it scrolls into view (ballistic, like a meter needle) and the same scale
 * is used everywhere, so scores compare at a glance.
 */
import { cn } from "@/lib/cn";

export function ScoreBar({
  label,
  value,
  color = "var(--color-court)",
  size = "md",
  showValue = true,
  className,
  hint,
}: {
  label: string;
  value: number;
  color?: string;
  size?: "sm" | "md";
  showValue?: boolean;
  className?: string;
  hint?: string;
}) {
  const v = Math.max(0, Math.min(10, value));
  return (
    <div className={cn("grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3", size === "sm" && "grid-cols-[minmax(0,4.6rem)_1fr_auto] gap-2.5", className)} title={hint}>
      <span className={cn("label truncate", size === "sm" && "!text-[0.75rem]")}>{label}</span>
      <span
        className={cn("relative overflow-hidden rounded-full bg-ink/8", size === "sm" ? "h-1.5" : "h-2.5")}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={10}
        aria-valuenow={v}
        aria-valuetext={`${v.toFixed(1)} out of 10`}
      >
        <span className="gauge-fill absolute inset-y-0 left-0 rounded-full" style={{ width: `${v * 10}%`, background: color }} />
      </span>
      {showValue && <span className={cn("num w-8 text-right font-bold text-ink", size === "sm" ? "text-xs" : "text-sm")}>{v.toFixed(1)}</span>}
    </div>
  );
}
