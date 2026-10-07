import type { Metadata } from "next";
import { parseFilters } from "@/lib/catalog/filters";
import { RacketsBrowser } from "@/components/catalog/RacketsBrowser";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Padel rackets and brands in 3D",
  description: "Choose a brand, then a racket. Filter padel rackets by shape, balance, weight, level and platform scores, and turn every one in 3D.",
  path: "/rackets",
});

export default async function RacketsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  return <RacketsBrowser initial={parseFilters(params)} title="Rackets and brands" crumbs={[{ name: "Home", href: "/" }, { name: "Rackets" }]} />;
}
