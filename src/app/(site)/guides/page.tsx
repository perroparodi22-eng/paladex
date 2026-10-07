import type { Metadata } from "next";
import Link from "next/link";
import { GUIDES } from "@/content/guides";
import { Breadcrumbs, Container, SectionHeading } from "@/components/layout/Section";
import { Icon } from "@/components/ui/Icon";
import { formatDate } from "@/lib/format";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Padel racket guides",
  description: "Plain-language guides to choosing a padel racket: shapes, balance, weight, core hardness, and how to inspect a racket in 3D.",
  path: "/guides",
});

export default function GuidesPage() {
  const topics = [...new Set(GUIDES.map((g) => g.topic))];
  return (
    <Container className="pb-16 pt-8">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Guides" }]} />
      <SectionHeading as="h1" title="Guides" intro="What the specs mean on court, explained in plain language and shown on 3D models." />
      <div className="space-y-12">
        {topics.map((t) => (
          <section key={t} aria-labelledby={`t-${t}`}>
            <h2 id={`t-${t}`} className="label mb-3 text-ink">
              {t}
            </h2>
            <ul className="divide-y divide-ink/8 border-y border-ink/8">
              {GUIDES.filter((g) => g.topic === t).map((g) => (
                <li key={g.slug}>
                  <Link href={`/guides/${g.slug}`} className="group grid gap-2 py-5 sm:grid-cols-[1fr_auto] sm:items-center">
                    <span>
                      <span className="block title text-3xl leading-none text-ink transition-colors group-hover:text-court">{g.title}</span>
                      <span className="mt-2 block max-w-2xl text-ink-2">{g.description}</span>
                    </span>
                    <span className="flex items-center gap-3 text-sm text-ink-3">
                      {g.minutes} min read · {formatDate(g.updated)}
                      <Icon name="arrowRight" size={18} className="transition-transform group-hover:translate-x-1" />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Container>
  );
}
