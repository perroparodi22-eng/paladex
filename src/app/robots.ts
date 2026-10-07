import type { MetadataRoute } from "next";
import { indexingAllowed, siteUrl } from "@/config/site";

/** Indexing stays off until NEXT_PUBLIC_ALLOW_INDEXING=true (the catalog holds sample data). */
export default function robots(): MetadataRoute.Robots {
  if (!indexingAllowed()) return { rules: [{ userAgent: "*", disallow: "/" }] };
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/admin", "/api/", "/go/", "/link-unavailable"] }],
    sitemap: siteUrl("/sitemap.xml"),
    host: siteUrl("/"),
  };
}
