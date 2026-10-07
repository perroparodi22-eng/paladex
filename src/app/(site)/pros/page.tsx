import type { Metadata } from "next";
import type { ProPlayer, RacketSummary } from "@/domain/types";
import { listRacketSummaries } from "@/server/repositories/rackets";
import { RacketCard } from "@/components/racket/RacketCard";
import { Breadcrumbs, Container, SectionHeading } from "@/components/layout/Section";
import { Reveal } from "@/components/ui/Reveal";
import { breadcrumbJsonLd, itemListJsonLd, jsonLdString, pageMetadata } from "@/lib/seo";

export const revalidate = 3600;

export const metadata: Metadata = pageMetadata({
  title: "Pro players' padel rackets",
  description: "The rackets the top padel players use, from Agustín Tapia and Arturo Coello to Ari Sánchez and Gemma Triay. Turn every one in 3D.",
  path: "/pros",
});

type Entry = { player: ProPlayer; racket: RacketSummary };

function byTour(rackets: RacketSummary[], tour: ProPlayer["tour"]): Entry[] {
  return rackets
    .flatMap((racket) => (racket.proPlayers ?? []).filter((p) => p.tour === tour).map((player) => ({ player, racket })))
    .sort((a, b) => a.player.order - b.player.order);
}

function Tour({ title, entries, id }: { title: string; entries: Entry[]; id: string }) {
  return (
    <Reveal as="section" className="mt-12" id={id}>
      <h2 className="display text-[clamp(1.8rem,3.4vw,2.6rem)]">{title}</h2>
      <ol className="mt-6 grid grid-cols-1 gap-x-4 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
        {entries.map(({ player, racket }, i) => (
          <li key={`${player.name}-${racket.slug}`} className="flex flex-col">
            <p className="mb-3 flex items-baseline gap-2 px-1">
              <span className="num text-sm text-ink-3">{String(i + 1).padStart(2, "0")}</span>
              <span className="title text-[1.15rem]">{player.name}</span>
            </p>
            <RacketCard racket={racket} className="flex-1" />
          </li>
        ))}
      </ol>
    </Reveal>
  );
}

export default async function ProsPage() {
  const all = await listRacketSummaries();
  const men = byTour(all, "men");
  const women = byTour(all, "women");
  return (
    <Container className="pb-16 pt-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdString([
            breadcrumbJsonLd([
              { name: "Home", path: "/" },
              { name: "Pro players", path: "/pros" },
            ]),
            itemListJsonLd("Pro players' padel rackets", [...men, ...women].map((e) => e.racket)),
          ]),
        }}
      />
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Pro players" }]} />
      <SectionHeading
        as="h1"
        title="Pro players' rackets"
        intro="What the top of the tour plays, in 3D. Players are matched to rackets from public lists as of early 2026; sponsors and editions change during the season, and some pros play a personalised version of the model shown."
      />
      <Tour id="men" title="Men's tour" entries={men} />
      <Tour id="women" title="Women's tour" entries={women} />
    </Container>
  );
}
