import type { Metadata } from "next";
import Link from "next/link";
import { Breadcrumbs, Container } from "@/components/layout/Section";
import { siteConfig } from "@/config/site";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: `About ${siteConfig.name}`,
  description: `${siteConfig.name} is a 3D-first padel racket database: inspect and choose rackets, with every spec explained and every source labelled.`,
  path: "/about",
});

export default function AboutPage() {
  return (
    <Container className="pb-16 pt-8">
      <Breadcrumbs items={[{ name: "Home", href: "/" }, { name: "About" }]} />
      <article className="mx-auto max-w-3xl">
        <h1 className="display text-[clamp(2.75rem,6vw,5rem)]">Choose a racket the way players actually do</h1>
        <div className="prose mt-8">
          <p>
            Players pick up a racket, turn it over, look along the edge and feel where the weight sits. Photos can&apos;t do that. {siteConfig.name} puts
            every racket on a 3D court, so you can turn it, zoom in and lay it next to another before you decide.
          </p>
          <h2>What we promise</h2>
          <ul>
            <li>
              <strong>Specs translated into decisions.</strong> Every term comes with what it means for your game.
            </li>
            <li>
              <strong>Labels you can trust.</strong> Manufacturer data, our own evaluations and illustrations are always marked as what they are. So are
              placeholder models and sample prices.
            </li>
            <li>
              <strong>Independent scores.</strong> We may earn commissions from retailers. That never changes how we score or rank.
            </li>
          </ul>
          <h2>Where we are</h2>
          <p>
            The catalog is growing. Some rackets have 3D models built from reference photos, some have placeholders, and specifications are verified
            step by step. If you spot an error,{" "}
            <Link href="/contact">tell us</Link>.
          </p>
        </div>
      </article>
    </Container>
  );
}
