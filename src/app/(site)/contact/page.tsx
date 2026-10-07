import type { Metadata } from "next";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { Icon } from "@/components/ui/Icon";
import { siteConfig } from "@/config/site";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Contact",
  description: `Contact ${siteConfig.name}: corrections, brand and retailer partnerships, 3D model licensing and press.`,
  path: "/contact",
});

const TOPICS = [
  ["Spec corrections", "Spotted a wrong weight, balance or material? Send the source and we'll verify it."],
  ["Brands and 3D models", "Manufacturers can supply official models and photography, which we label as official."],
  ["Retailers and affiliates", "Partnerships and price feeds."],
  ["Privacy requests", "Questions about the data described in our privacy policy."],
];

export default function ContactPage() {
  return (
    <Container className="pb-16 pt-8">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "Contact" }]} />
      <div className="mx-auto max-w-3xl">
        <h1 className="display text-[clamp(2.75rem,6vw,5rem)]">Contact</h1>
        <p className="mt-4 text-lg text-ink/85">One inbox for everything. We read every message.</p>
        <a href={`mailto:${siteConfig.contactEmail}`} className="btn btn-primary mt-6">
          <Icon name="arrowRight" size={18} /> {siteConfig.contactEmail}
        </a>
        <p className="mt-2 text-xs text-ink-3">Placeholder address: set the real one in src/config/site.ts.</p>
        <ul className="mt-10 divide-y divide-ink/8 border-y border-ink/8">
          {TOPICS.map(([t, d]) => (
            <li key={t} className="grid gap-1 py-4 sm:grid-cols-[14rem_1fr]">
              <span className="font-semibold">{t}</span>
              <span className="text-ink-2">{d}</span>
            </li>
          ))}
        </ul>
      </div>
    </Container>
  );
}
