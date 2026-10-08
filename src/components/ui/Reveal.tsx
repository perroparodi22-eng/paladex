"use client";
/**
 * Reveal once. Content below the fold starts tilted back in depth and settles
 * forward the first time it scrolls into view, then stays visible: scrolling
 * back and forth never hides it again. Anything already on screen when the
 * page loads is left alone, and reduced motion turns the effect off.
 */
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

export function Reveal({
  children,
  className,
  beat = 0,
  as = "div",
  id,
}: {
  children: ReactNode;
  className?: string;
  /** Stagger step (multiplied by 90ms). */
  beat?: number;
  as?: "div" | "section" | "li";
  id?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const Tag = as as "div";
  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (el.getBoundingClientRect().top < window.innerHeight * 0.95) return;
    el.dataset.reveal = "pending";
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          el.dataset.reveal = "in";
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.1 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} id={id} className={className} style={{ "--beat": beat } as CSSProperties}>
      {children}
    </Tag>
  );
}
