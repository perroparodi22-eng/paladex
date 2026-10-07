import type { Metadata } from "next";
import { listRacketSummaries } from "@/server/repositories/rackets";
import { ShowroomExperience } from "@/components/showroom/ShowroomExperience";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { MODEL_RANK } from "@/lib/catalog/filters";
import { pageMetadata } from "@/lib/seo";

export const revalidate = 3600;

export const metadata: Metadata = pageMetadata({
  title: "3D padel racket showroom",
  description: "Browse padel rackets on a floodlit 3D court. Turn each racket, zoom in, switch models, filter by brand and style, and jump to details or retailers.",
  path: "/showroom",
});

export default async function ShowroomPage({ searchParams }: { searchParams: Promise<{ racket?: string }> }) {
  const [all, p] = await Promise.all([listRacketSummaries(), searchParams]);
  const rackets = [...all].sort((a, b) => MODEL_RANK[b.modelStatus] - MODEL_RANK[a.modelStatus] || Number(b.featured) - Number(a.featured));
  const initial = p.racket && rackets.some((r) => r.slug === p.racket) ? p.racket : rackets[0]?.slug;
  return (
    <Container wide className="pb-16 pt-6">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "3D Showroom" }]} />
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <h1 className="display text-[clamp(2.5rem,5vw,4.25rem)]">The 3D showroom</h1>
        <p className="max-w-md text-sm text-ink-2">
          Use ← → in the strip to switch rackets. Drag to turn, pinch or scroll to zoom. Every model is labelled with where it comes from.
        </p>
      </div>
      <ShowroomExperience rackets={rackets} initialSlug={initial} />
    </Container>
  );
}
