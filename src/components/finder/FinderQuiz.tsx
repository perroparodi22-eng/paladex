"use client";
/**
 * Find My Racket: eight short questions, then matches explained factor by
 * factor and shown in 3D. Answers live in the URL so results can be shared.
 */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { RacketShape, RacketSummary } from "@/domain/types";
import { MODEL_STATUS_INFO, SHAPE_INFO } from "@/domain/vocab";
import { recommend, type FinderAnswers } from "@/lib/recommend/engine";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { RacketPoster } from "@/components/racket/RacketPoster";
import { Icon } from "@/components/ui/Icon";
import { formatPrice } from "@/lib/format";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

type Key = keyof FinderAnswers;
interface Question {
  key: Key;
  title: string;
  help: string;
  options: Array<{ value: string; label: string; sub?: string }>;
}

const QUESTIONS: Question[] = [
  {
    key: "level",
    title: "What's your level?",
    help: "Be honest. A demanding racket won't make a developing game better.",
    options: [
      { value: "beginner", label: "Beginner", sub: "Learning the basics" },
      { value: "intermediate", label: "Intermediate", sub: "Play regularly, consistent strokes" },
      { value: "advanced", label: "Advanced", sub: "Strong technique and swing speed" },
    ],
  },
  {
    key: "game",
    title: "How would you describe your game?",
    help: "Think about where you usually win your points.",
    options: [
      { value: "defensive", label: "Defensive", sub: "Back glass, lobs and resets" },
      { value: "balanced", label: "Balanced", sub: "Attack and defend in the same rally" },
      { value: "aggressive", label: "Aggressive", sub: "Take the net, finish overhead" },
    ],
  },
  {
    key: "priority",
    title: "What matters most?",
    help: "If you could only improve one thing.",
    options: [
      { value: "power", label: "Power", sub: "Harder smashes and volleys" },
      { value: "control", label: "Control", sub: "Ball goes where I aim" },
      { value: "maneuverability", label: "Maneuverability", sub: "Quick hands at the net" },
      { value: "balance", label: "A balance", sub: "Power and control together" },
    ],
  },
  {
    key: "shape",
    title: "What racket shape do you prefer?",
    help: "Round = control and forgiveness · Diamond = power, high sweet spot.",
    options: [
      { value: "round", label: "Round" },
      { value: "teardrop", label: "Teardrop" },
      { value: "diamond", label: "Diamond" },
      { value: "any", label: "No preference" },
    ],
  },
  {
    key: "weight",
    title: "Preferred weight?",
    help: "Lighter is quicker and easier on the arm. Heavier is more stable.",
    options: [
      { value: "light", label: "Light", sub: "Around 345–355 g" },
      { value: "medium", label: "Medium", sub: "Around 355–368 g" },
      { value: "heavy", label: "Heavy", sub: "368 g and up" },
      { value: "any", label: "No preference" },
    ],
  },
  {
    key: "budget",
    title: "What's your budget?",
    help: "Sample prices while the catalog is in development.",
    options: [
      { value: "100", label: "Up to €100" },
      { value: "200", label: "Up to €200" },
      { value: "300", label: "Up to €300" },
      { value: "none", label: "No limit" },
    ],
  },
  {
    key: "armCare",
    title: "Any elbow or shoulder discomfort?",
    help: "Softer cores and head-light rackets are kinder to the arm.",
    options: [
      { value: "yes", label: "Yes, go easy on my arm" },
      { value: "no", label: "No" },
    ],
  },
  {
    key: "current",
    title: "What racket are you using now?",
    help: "Optional. We'll leave it out of the results and show how each match differs from it.",
    options: [],
  },
];

type Raw = Partial<Record<Key, string>>;

function toAnswers(raw: Raw): FinderAnswers | null {
  if (!raw.level || !raw.game || !raw.priority || !raw.shape || !raw.weight || !raw.budget || !raw.armCare) return null;
  return {
    level: raw.level as FinderAnswers["level"],
    game: raw.game as FinderAnswers["game"],
    priority: raw.priority as FinderAnswers["priority"],
    shape: raw.shape as RacketShape | "any",
    weight: raw.weight as FinderAnswers["weight"],
    budget: raw.budget === "none" ? null : Number(raw.budget),
    armCare: raw.armCare === "yes",
    current: raw.current && raw.current !== "none" ? raw.current : null,
  };
}

export function FinderQuiz({ rackets, initial }: { rackets: RacketSummary[]; initial: Raw }) {
  const [raw, setRaw] = useState<Raw>(initial);
  const firstUnanswered = QUESTIONS.findIndex((q) => raw[q.key] === undefined);
  const [step, setStep] = useState(firstUnanswered === -1 ? QUESTIONS.length : Math.max(0, firstUnanswered));
  const answers = toAnswers({ ...raw, current: raw.current ?? "none" });
  const done = step >= QUESTIONS.length && !!answers;
  const results = useMemo(() => (done && answers ? recommend(rackets, answers, 6) : []), [done, answers, rackets]);
  const [selected, setSelected] = useState(0);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    if (!done || !results.length) return;
    track("finder_completed", { top: results[0].racket.slug, count: results.length });
    const p = new URLSearchParams(raw as Record<string, string>);
    window.history.replaceState(null, "", `/finder?${p}`);
    setSelected(0);
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps

  const answer = (key: Key, value: string) => {
    if (!started) {
      setStarted(true);
      track("finder_started", {});
    }
    setRaw((r) => ({ ...r, [key]: value }));
    setStep((s) => s + 1);
  };

  if (!done) {
    const q = QUESTIONS[Math.min(step, QUESTIONS.length - 1)];
    return (
      <div className="card-sky grain mx-auto max-w-4xl rounded-[36px] p-6 shadow-soft sm:p-10">
        <div className="relative z-[2]">
        {/* Progress: a replay timeline filling in. */}
        <ol className="mb-8 flex gap-1.5" aria-label={`Question ${step + 1} of ${QUESTIONS.length}`}>
          {QUESTIONS.map((qq, i) => (
            <li key={qq.key} className={cn("h-2 flex-1 rounded-full transition-colors duration-500", i < step ? "bg-ink/50" : i === step ? "bg-court" : "bg-white/10")} />
          ))}
        </ol>
        <p className="label text-ink">
          Question <span className="num">{step + 1}</span> of {QUESTIONS.length}
        </p>
        <h2 className="display mt-2 text-[clamp(2.25rem,5vw,3.75rem)]">{q.title}</h2>
        <p className="mt-3 text-ink">{q.help}</p>
        {q.key === "current" ? (
          <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]">
            <select className="field h-12 rounded-full" value={raw.current ?? ""} onChange={(e) => setRaw((r) => ({ ...r, current: e.target.value || undefined }))} aria-label="Your current racket">
              <option value="">Choose your current racket (optional)</option>
              <option value="none">None, or not listed</option>
              {rackets.map((r) => (
                <option key={r.slug} value={r.slug}>
                  {r.fullName}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-primary h-12" onClick={() => answer("current", raw.current ?? "none")}>
              See my matches <Icon name="arrowRight" size={18} />
            </button>
          </div>
        ) : (
          <div className={cn("mt-7 grid gap-3", q.options.length === 4 ? "sm:grid-cols-2" : "sm:grid-cols-3")} role="radiogroup" aria-label={q.title}>
            {q.options.map((o) => (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={raw[q.key] === o.value}
                onClick={() => answer(q.key, o.value)}
                className={cn(
                  "group rounded-3xl border p-5 text-left shadow-soft transition-[transform,background-color,border-color,box-shadow] duration-300 [transition-timing-function:var(--ease-spring)] hover:-translate-y-0.5 hover:shadow-lift",
                  raw[q.key] === o.value ? "border-court bg-court text-on-court" : "border-ink/6 bg-surface hover:border-court/40",
                )}
              >
                <span className={cn("title block text-[1.45rem] leading-tight", raw[q.key] === o.value ? "text-on-court" : "text-ink")}>{o.label}</span>
                {o.sub && <span className={cn("mt-1.5 block text-sm", raw[q.key] === o.value ? "text-on-court/70" : "text-ink-2")}>{o.sub}</span>}
              </button>
            ))}
          </div>
        )}
        <div className="mt-8 flex items-center justify-between">
          <button type="button" className="btn btn-ghost" disabled={step === 0} onClick={() => setStep((s) => Math.max(0, s - 1))}>
            <Icon name="arrowLeft" size={18} /> Back
          </button>
          {raw[q.key] !== undefined && q.key !== "current" && (
            <button type="button" className="btn btn-secondary" onClick={() => setStep((s) => s + 1)}>
              Next <Icon name="arrowRight" size={18} />
            </button>
          )}
        </div>
        </div>
      </div>
    );
  }

  const pick = results[selected] ?? results[0];
  if (!pick) {
    return (
      <div className="plate p-8 text-center">
        <p className="title text-3xl">No matches</p>
        <button type="button" className="btn btn-primary mt-4" onClick={() => setStep(0)}>
          Start again
        </button>
      </div>
    );
  }
  const r = pick.racket;
  const interactive = MODEL_STATUS_INFO[r.modelStatus].interactive;
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-ink-2">
          Based on your answers: <span className="text-ink">{raw.level}</span> · <span className="text-ink">{raw.game}</span> ·{" "}
          <span className="text-ink">{raw.priority === "balance" ? "balanced" : raw.priority}</span> priority
        </p>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => {
            setRaw({});
            setStep(0);
            window.history.replaceState(null, "", "/finder");
          }}
        >
          <Icon name="reset" size={16} /> Start again
        </button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="relative h-[60svh] min-h-[420px] overflow-hidden rounded-[28px] shadow-lift">
          <Racket3DViewer
            racket={{
              slug: r.slug,
              fullName: r.fullName,
              shape: r.shape,
              visual: r.visual,
              imageUrl: r.imageUrl,
              imageAlt: r.imageAlt,
              model: interactive ? { status: r.modelStatus, url: r.modelUrl, previewUrl: r.modelPreviewUrl, posterUrl: null, supportsExplode: true } : null,
            }}
            variant="showroom"
            loadStrategy="eager"
            className="absolute inset-0"
          />
          <div className="pointer-events-none absolute right-4 top-14 z-30">
            <p className="flex items-baseline gap-1.5 rounded-full bg-ball px-4 py-1.5 text-ball-deep shadow-lift">
              <span className="num display text-[2.2rem]">{pick.match}%</span>
              <span className="text-sm font-semibold">match</span>
            </p>
          </div>
        </div>
        <div className="plate p-6">
          <p className="label">
            {selected === 0 ? "Your best match" : `Match #${selected + 1}`} · {r.brand.name}
          </p>
          <h3 className="display mt-1 text-5xl">{r.name}</h3>
          <p className="mt-2 text-sm text-ink-2">
            {SHAPE_INFO[r.shape].label} · {formatPrice(r.priceFrom ?? r.indicativePrice, { compact: true })}
          </p>
          <div className="mt-4">
            <p className="label mb-1.5">Why it fits</p>
            <ul className="space-y-1.5 text-sm">
              {pick.reasons.map((x) => (
                <li key={x} className="flex gap-2">
                  <Icon name="check" size={16} className="mt-0.5 shrink-0 text-ok" /> {x}
                </li>
              ))}
            </ul>
          </div>
          {pick.strengths.length > 0 && (
            <p className="mt-3 text-sm">
              <span className="label mr-2">Strengths</span>
              <span className="text-ink">{pick.strengths.join(" · ")}</span>
            </p>
          )}
          {pick.drawbacks.length > 0 && (
            <div className="mt-3">
              <p className="label mb-1.5">Potential drawbacks</p>
              <ul className="space-y-1 text-sm text-ink-2">
                {pick.drawbacks.map((x) => (
                  <li key={x} className="flex gap-2">
                    <Icon name="minus" size={16} className="mt-0.5 shrink-0 text-warn" /> {x}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {pick.versusCurrent.length > 0 && (
            <p className="mt-3 text-sm text-ink-2">
              <span className="label mr-2">Vs your racket</span>
              {pick.versusCurrent.join(" · ")}
            </p>
          )}
          <div className="mt-5 grid grid-cols-2 gap-2">
            <Link href={`/rackets/${r.slug}`} className="btn btn-primary">
              View racket
            </Link>
            <Link href={`/rackets/${r.slug}#where-to-buy`} className="btn btn-secondary">
              Where to buy
            </Link>
          </div>
        </div>
      </div>
      <ol className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" aria-label="All matches">
        {results.map((res, i) => (
          <li key={res.racket.slug}>
            <button
              type="button"
              onClick={() => setSelected(i)}
              aria-pressed={i === selected}
              className={cn(
                "relative flex h-full w-full flex-col overflow-hidden rounded-3xl border bg-surface p-2.5 text-left shadow-soft transition-[box-shadow,transform,border-color] duration-300 hover:-translate-y-0.5 hover:shadow-lift",
                i === selected ? "border-court ring-2 ring-court" : "border-ink/6",
              )}
            >
              <span className="card-sky relative block h-28 rounded-2xl">
                <RacketPoster racket={res.racket} sizes="160px" className="absolute inset-0 p-2" />
              </span>
              <span className="num mt-2 w-fit rounded-full bg-ball px-2.5 py-0.5 text-lg font-bold text-ball-deep">{res.match}%</span>
              <span className="mt-1 truncate text-sm font-semibold">{res.racket.name}</span>
              <span className="truncate text-xs text-ink-3">{res.racket.brand.name}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="mt-6 text-center text-xs text-ink-3">
        Match percentages come from a transparent, rules-based model using platform scores (sample data). They&apos;re a starting point, not a verdict.
      </p>
    </div>
  );
}
