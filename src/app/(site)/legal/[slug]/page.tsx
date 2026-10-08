import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LEGAL_PAGES, getLegalPage } from "@/content/legal";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { formatDate } from "@/lib/format";
import { pageMetadata } from "@/lib/seo";

export function generateStaticParams() {
  return LEGAL_PAGES.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const p = getLegalPage(slug);
  if (!p) return { title: "Not found" };
  return pageMetadata({ title: p.title, description: p.description, path: `/legal/${p.slug}` });
}

export default async function LegalPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = getLegalPage(slug);
  if (!page) notFound();
  return (
    <Container className="pb-16 pt-8">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: page.title }]} />
      <article className="mx-auto max-w-3xl">
        <h1 className="display text-[clamp(2.5rem,6vw,4.25rem)]">{page.title}</h1>
        <p className="mt-3 text-sm text-ink-3">Last updated {formatDate(page.updated)}</p>
        <p className="mt-4 rounded-xl border border-warn/40 px-3 py-2 text-sm text-warn">
          Draft text. To be reviewed by a qualified professional before launch.
        </p>
        <div className="prose mt-8">
          {page.sections.map((s) => (
            <section key={s.heading}>
              <h2>{s.heading}</h2>
              {s.paragraphs.map((p) => (
                <p key={p}>{p}</p>
              ))}
              {s.list && (
                <ul>
                  {s.list.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
        <nav aria-label="Other policies" className="mt-12 flex flex-wrap gap-2">
          {LEGAL_PAGES.filter((p) => p.slug !== page.slug).map((p) => (
            <Link key={p.slug} href={`/legal/${p.slug}`} className="chip">
              {p.title}
            </Link>
          ))}
        </nav>
      </article>
    </Container>
  );
}
