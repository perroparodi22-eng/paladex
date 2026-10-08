import type { Metadata } from "next";
import { listRacketSummaries } from "@/server/repositories/rackets";
import { FinderQuiz } from "@/components/finder/FinderQuiz";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Find my padel racket: an 8-question finder",
  description: "Answer eight questions about your level, game, priorities and budget. Get padel racket matches explained factor by factor and shown in 3D.",
  path: "/finder",
});

const KEYS = ["level", "game", "priority", "shape", "weight", "budget", "armCare", "current"] as const;
const ALLOWED: Record<string, string[]> = {
  level: ["beginner", "intermediate", "advanced"],
  game: ["defensive", "balanced", "aggressive"],
  priority: ["power", "control", "maneuverability", "balance"],
  shape: ["round", "teardrop", "diamond", "any"],
  weight: ["light", "medium", "heavy", "any"],
  budget: ["100", "200", "300", "none"],
  armCare: ["yes", "no"],
};

export default async function FinderPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [rackets, p] = await Promise.all([listRacketSummaries(), searchParams]);
  const initial: Record<string, string> = {};
  for (const k of KEYS) {
    const v = Array.isArray(p[k]) ? p[k]![0] : p[k];
    if (typeof v !== "string") continue;
    if (k === "current" ? v === "none" || rackets.some((r) => r.slug === v) : ALLOWED[k]?.includes(v)) initial[k] = v;
  }
  return (
    <Container className="pb-16 pt-8">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Find my racket" }]} />
      <h1 className="sr-only">Find my padel racket</h1>
      <FinderQuiz rackets={rackets} initial={initial} />
    </Container>
  );
}
