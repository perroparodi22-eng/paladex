/**
 * SEO helpers: page metadata and JSON-LD structured data.
 * Offers are only included in Product structured data when they are real
 * (not demo); ratings only when genuine user reviews exist.
 */
import type { Metadata } from "next";
import type { Racket, RacketSummary } from "@/domain/types";
import { siteConfig, siteUrl } from "@/config/site";
import { SHAPE_INFO } from "@/domain/vocab";

export function pageMetadata(opts: {
  title: string;
  description: string;
  path: string;
  image?: string;
  noindex?: boolean;
}): Metadata {
  const url = siteUrl(opts.path);
  return {
    title: opts.title,
    description: opts.description,
    alternates: { canonical: url },
    openGraph: {
      title: opts.title,
      description: opts.description,
      url,
      siteName: siteConfig.name,
      type: "website",
      locale: "en_GB",
      ...(opts.image ? { images: [{ url: opts.image, width: 1200, height: 630 }] } : {}),
    },
    twitter: { card: "summary_large_image", title: opts.title, description: opts.description },
    ...(opts.noindex ? { robots: { index: false, follow: true } } : {}),
  };
}

type JsonLd = Record<string, unknown>;

export function productJsonLd(r: Racket): JsonLd {
  const realOffers = r.offers.filter((o) => !o.isDemo && !o.linkIsPlaceholder && o.available);
  const props = [
    { name: "Shape", value: SHAPE_INFO[r.specs.shape].label },
    r.specs.weightMinG && { name: "Weight", value: `${r.specs.weightMinG}–${r.specs.weightMaxG} g` },
    r.specs.balance && { name: "Balance", value: r.specs.balance },
    r.specs.thicknessMm && { name: "Profile", value: `${r.specs.thicknessMm} mm` },
    r.specs.faceMaterial && { name: "Face", value: r.specs.faceMaterial },
    r.specs.coreMaterial && { name: "Core", value: r.specs.coreMaterial },
    r.model && r.model.status !== "unavailable" && { name: "3D model", value: r.model.status },
  ].filter(Boolean);
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: r.fullName,
    brand: { "@type": "Brand", name: r.brand.name },
    description: r.shortDescription,
    category: "Padel racket",
    url: siteUrl(`/rackets/${r.slug}`),
    ...(r.images.length ? { image: r.images.map((i) => siteUrl(i.url)) } : {}),
    ...(r.year ? { releaseDate: String(r.year) } : {}),
    additionalProperty: props.map((p) => ({ "@type": "PropertyValue", ...(p as object) })),
    ...(r.model?.url && r.model.status !== "unavailable"
      ? { subjectOf: { "@type": "3DModel", name: `${r.fullName} 3D model`, encodingFormat: "model/gltf-binary", contentUrl: siteUrl(r.model.url) } }
      : {}),
    ...(realOffers.length
      ? {
          offers: {
            "@type": "AggregateOffer",
            priceCurrency: realOffers[0].price.currency,
            lowPrice: (Math.min(...realOffers.map((o) => o.price.amountCents)) / 100).toFixed(2),
            highPrice: (Math.max(...realOffers.map((o) => o.price.amountCents)) / 100).toFixed(2),
            offerCount: realOffers.length,
          },
        }
      : {}),
    ...(r.userRating && r.userRating.count > 0
      ? { aggregateRating: { "@type": "AggregateRating", ratingValue: r.userRating.average, reviewCount: r.userRating.count, bestRating: 5 } }
      : {}),
  };
}

export function breadcrumbJsonLd(items: Array<{ name: string; path: string }>): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({ "@type": "ListItem", position: i + 1, name: it.name, item: siteUrl(it.path) })),
  };
}

export function itemListJsonLd(name: string, rackets: RacketSummary[]): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name,
    itemListElement: rackets.slice(0, 30).map((r, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: siteUrl(`/rackets/${r.slug}`),
      name: r.fullName,
    })),
  };
}

export function websiteJsonLd(): JsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteConfig.name,
    url: siteUrl("/"),
    potentialAction: {
      "@type": "SearchAction",
      target: { "@type": "EntryPoint", urlTemplate: `${siteUrl("/rackets")}?q={search_term_string}` },
      "query-input": "required name=search_term_string",
    },
  };
}

/** Serialize JSON-LD safely for a <script> tag (no closing-tag injection). */
export function jsonLdString(data: JsonLd | JsonLd[]): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
