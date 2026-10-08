import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getBrand, listBrands } from "@/server/repositories/brands";
import { EMPTY_FILTERS } from "@/lib/catalog/filters";
import { RacketsBrowser } from "@/components/catalog/RacketsBrowser";
import { pageMetadata } from "@/lib/seo";

export const revalidate = 3600;

export async function generateStaticParams() {
  const brands = await listBrands();
  return brands.map((b) => ({ slug: b.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const b = await getBrand(slug);
  if (!b) return { title: "Brand not found" };
  return pageMetadata({
    title: `${b.name} padel rackets in 3D`,
    description: `${b.name} padel rackets: turn each one in 3D and see what its shape and balance mean for your game. ${b.description}`.slice(0, 300),
    path: `/brands/${b.slug}`,
  });
}

/** A brand's own address: the same rackets browser, opened with this brand chosen. */
export default async function BrandPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const brand = await getBrand(slug);
  if (!brand) notFound();
  return (
    <RacketsBrowser
      initial={{ ...EMPTY_FILTERS, brands: [brand.slug] }}
      title="Rackets and brands"
      crumbs={[{ name: "Home", href: "/" }, { name: "Rackets", href: "/rackets" }, { name: brand.name }]}
    />
  );
}
