import type { Metadata } from "next";
import Link from "next/link";
import { Container } from "@/components/layout/Section";
import { Icon } from "@/components/ui/Icon";

export const metadata: Metadata = { title: "Retailer link not active", robots: { index: false, follow: false } };

const COPY: Record<string, { title: string; body: string }> = {
  placeholder: {
    title: "This retailer link isn't active yet",
    body: "This shop and price are sample data while the site is being built. The affiliate link is still a placeholder, so there's nowhere to send you yet. Your click was counted anonymously.",
  },
  unsafe: {
    title: "We stopped this redirect",
    body: "The retailer link didn't pass our safety checks, so we didn't follow it. We'll review it.",
  },
  inactive: {
    title: "This offer is no longer available",
    body: "The retailer or offer has been switched off. Try another shop on the racket page.",
  },
  missing: {
    title: "Offer not found",
    body: "This offer doesn't exist, or it has been removed.",
  },
};

export default async function LinkUnavailable({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const p = await searchParams;
  const c = COPY[p.reason ?? "missing"] ?? COPY.missing;
  const racket = p.racket && /^[a-z0-9-]{1,80}$/.test(p.racket) ? p.racket : null;
  return (
    <Container className="py-24">
      <div className="plate mx-auto max-w-xl p-8">
        <Icon name="link" size={28} className="text-court" />
        <h1 className="display mt-4 text-5xl">{c.title}</h1>
        {p.retailer && (
          <p className="mt-3 text-sm text-ink-2">
            Retailer: <span className="text-ink">{p.retailer.slice(0, 60)}</span>
            {p.name && (
              <>
                {" "}
                · Racket: <span className="text-ink">{p.name.slice(0, 80)}</span>
              </>
            )}
          </p>
        )}
        <p className="mt-4 leading-relaxed text-ink/85">{c.body}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {racket && (
            <Link href={`/rackets/${racket}`} className="btn btn-primary">
              Back to the racket
            </Link>
          )}
          <Link href="/rackets" className="btn btn-secondary">
            Browse rackets
          </Link>
        </div>
      </div>
    </Container>
  );
}
