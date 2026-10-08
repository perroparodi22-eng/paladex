"use client";
/**
 * Head-to-head gauges: identical meters in a row, each with one needle per
 * racket. Needles swing in with mass and overshoot when the row scrolls into
 * view (never an instant jump), then settle on the value.
 */
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

export interface GaugeNeedle {
  value: number;
  color: string;
  label: string;
}

const SWEEP = 180;

function angle(v: number) {
  return -90 + (Math.max(0, Math.min(10, v)) / 10) * SWEEP;
}

export function NeedleGauge({ title, needles, className, live }: { title: string; needles: GaugeNeedle[]; className?: string; live: boolean }) {
  return (
    <figure className={cn("flex flex-col items-center", className)}>
      <svg viewBox="0 0 120 72" className="w-full max-w-[180px]" role="img" aria-label={`${title}: ${needles.map((n) => `${n.label} ${n.value.toFixed(1)}`).join(", ")} out of 10`}>
        <path d="M12 64a48 48 0 0 1 96 0" fill="none" stroke="rgb(17 22 58 / 0.1)" strokeWidth="9" strokeLinecap="round" />
        {Array.from({ length: 11 }, (_, i) => {
          const a = ((-180 + i * 18) * Math.PI) / 180;
          const r1 = i % 5 === 0 ? 34 : 37;
          return (
            <line
              key={i}
              x1={60 + Math.cos(a) * r1}
              y1={64 + Math.sin(a) * r1}
              x2={60 + Math.cos(a) * 40}
              y2={64 + Math.sin(a) * 40}
              stroke="rgb(17 22 58 / 0.35)"
              strokeWidth={i % 5 === 0 ? 1.6 : 1}
              strokeLinecap="round"
            />
          );
        })}
        {needles.map((n, i) => (
          <g
            key={i}
            style={{
              transform: `rotate(${live ? angle(n.value) : -90}deg)`,
              transformOrigin: "60px 64px",
              transition: `transform 1.4s cubic-bezier(0.22, 1, 0.36, 1) ${i * 120}ms`,
            }}
          >
            <line x1="60" y1="64" x2="60" y2="22" stroke={n.color} strokeWidth="3" strokeLinecap="round" />
          </g>
        ))}
        <circle cx="60" cy="64" r="5" fill="#11163a" />
      </svg>
      <figcaption className="mt-1 text-center">
        <span className="block text-[0.8125rem] font-semibold text-ink [--rond:100]">{title}</span>
        <span className="num mt-0.5 flex justify-center gap-2 text-sm font-bold">
          {needles.map((n, i) => (
            <span key={i} style={{ color: n.color }}>
              {n.value.toFixed(1)}
            </span>
          ))}
        </span>
      </figcaption>
    </figure>
  );
}

/** A row of gauges that swing in together when scrolled into view. */
export function GaugeRow({ rows, className }: { rows: Array<{ title: string; needles: GaugeNeedle[] }>; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setLive(true);
      return;
    }
    const io = new IntersectionObserver(
      (e) => {
        if (e.some((x) => x.isIntersecting)) {
          setLive(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={cn("grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-4", className)}>
      {rows.map((r) => (
        <NeedleGauge key={r.title} title={r.title} needles={r.needles} live={live} />
      ))}
    </div>
  );
}
