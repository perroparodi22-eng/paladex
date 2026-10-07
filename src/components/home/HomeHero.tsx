"use client";
/**
 * The first viewport: a racket in a black studio, turning slowly under one
 * soft light. Drag it, or use the arrows below it. The copy stays small and
 * still; the racket is the hero. The camera frames the racket in the space
 * the copy leaves free, on any screen.
 */
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Racket3DViewer, type ViewerRacket } from "@/components/three/Racket3DViewer";
import { ViewerBridgeProvider } from "@/components/three/ViewerBridge";
import { Icon } from "@/components/ui/Icon";

const HEADER = 64;

export function HomeHero({ racket, racketHref, caption }: { racket: ViewerRacket; racketHref: string; caption: ReactNode }) {
  const section = useRef<HTMLElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const [insets, setInsets] = useState<{ top: number; left: number }>({ top: HEADER, left: 0 });

  useEffect(() => {
    const measure = () => {
      const s = section.current?.getBoundingClientRect();
      const c = copy.current?.getBoundingClientRect();
      if (!s || !c) return;
      const wide = window.matchMedia("(min-width: 1024px)").matches;
      const next = wide ? { top: HEADER, left: Math.round(c.right - s.left) } : { top: Math.round(c.bottom - s.top + 8), left: 0 };
      setInsets((cur) => (cur.top === next.top && cur.left === next.left ? cur : next));
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (section.current) ro.observe(section.current);
    if (copy.current) ro.observe(copy.current);
    return () => ro.disconnect();
  }, []);

  return (
    <section ref={section} aria-labelledby="hero-title" className="stage-sky relative isolate -mt-16 min-h-[100dvh] overflow-hidden">
      <ViewerBridgeProvider>
        <Racket3DViewer
          racket={racket}
          variant="hero"
          loadStrategy="eager"
          priorityPoster
          stage
          className="absolute inset-0"
          frameInsets={insets}
          chromeTop={HEADER + 12}
        />

        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 px-4 pt-[128px] sm:px-6 lg:inset-y-0 lg:flex lg:items-center lg:px-10 lg:pt-0">
          <div ref={copy} className="pointer-events-auto max-w-[30rem]">
            <h1 id="hero-title" className="display text-[clamp(2.4rem,5vw,4.2rem)]">
              Every padel racket, in 3D.
            </h1>
            <p className="mt-4 max-w-[26rem] text-[1.0625rem] leading-relaxed text-ink-2">
              Pick a brand, turn any racket in your hand, and see what its shape and balance mean for your game.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href="/rackets" className="btn btn-primary">
                Browse rackets <Icon name="arrowRight" size={18} />
              </Link>
              <Link href="/finder" className="btn btn-secondary">
                Find my racket
              </Link>
            </div>
            <p className="mt-8 hidden text-sm text-ink-3 lg:block">
              On stage: {caption}.{" "}
              <Link href={racketHref} className="text-ink-2 underline underline-offset-4 hover:text-ink">
                Open its page
              </Link>
            </p>
          </div>
        </div>
      </ViewerBridgeProvider>
    </section>
  );
}
