import type { MetadataRoute } from "next";
import { siteUrl } from "@/config/site";
import { listPublishedSlugs } from "@/server/repositories/rackets";
import { listBrands } from "@/server/repositories/brands";
import { COLLECTIONS } from "@/lib/collections";
import { GUIDES } from "@/content/guides";
import { LEGAL_PAGES } from "@/content/legal";

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [slugs, brands] = await Promise.all([listPublishedSlugs(), listBrands()]);
  const now = new Date();
  return [
    { url: siteUrl("/"), lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: siteUrl("/rackets"), lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: siteUrl("/showroom"), lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: siteUrl("/finder"), lastModified: now, changeFrequency: "monthly", priority: 0.8 },
    { url: siteUrl("/pros"), lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: siteUrl("/guides"), lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    ...slugs.map((s) => ({ url: siteUrl(`/rackets/${s.slug}`), lastModified: new Date(s.updatedAt), changeFrequency: "weekly" as const, priority: 0.8 })),
    ...brands.filter((b) => (b.racketCount ?? 0) > 0).map((b) => ({ url: siteUrl(`/brands/${b.slug}`), lastModified: now, changeFrequency: "weekly" as const, priority: 0.6 })),
    ...COLLECTIONS.map((c) => ({ url: siteUrl(`/collections/${c.slug}`), lastModified: now, changeFrequency: "weekly" as const, priority: 0.7 })),
    ...GUIDES.map((g) => ({ url: siteUrl(`/guides/${g.slug}`), lastModified: new Date(g.updated), changeFrequency: "monthly" as const, priority: 0.6 })),
    ...LEGAL_PAGES.map((l) => ({ url: siteUrl(`/legal/${l.slug}`), lastModified: new Date(l.updated), changeFrequency: "yearly" as const, priority: 0.2 })),
    { url: siteUrl("/about"), lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: siteUrl("/contact"), lastModified: now, changeFrequency: "yearly", priority: 0.3 },
  ];
}
