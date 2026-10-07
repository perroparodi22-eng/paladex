"use client";
/** Loading pill over the poster, with a real percentage when it is known. */
export function Racket3DLoadingState({ progress, label }: { progress: number | null; label: string }) {
  const pct = progress === null ? null : Math.round(progress * 100);
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex justify-center p-4" role="status" aria-live="polite">
      <div className="plate flex w-full max-w-xs items-center gap-3 rounded-full px-4 py-2.5">
        <span className="text-[0.8125rem] font-semibold whitespace-nowrap text-ink [--rond:100]">{label}</span>
        <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
          {pct === null ? (
            <div className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-court motion-safe:animate-[hint-drift_1.4s_ease-in-out_infinite]" />
          ) : (
            <div className="absolute inset-y-0 left-0 rounded-full bg-court transition-[width] duration-200" style={{ width: `${pct}%` }} />
          )}
        </div>
        {pct !== null && <span className="num text-[0.8125rem] font-semibold text-ink-2">{pct}%</span>}
      </div>
    </div>
  );
}
