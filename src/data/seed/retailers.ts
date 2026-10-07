/**
 * Demo retailers. They are deliberately generic ("Store A/B/C"), point at
 * example.com and carry the AFFILIATE_URL_HERE placeholder, so nothing can be
 * mistaken for a live partnership. Replace them in /admin/retailers.
 */
export const AFFILIATE_PLACEHOLDER = "AFFILIATE_URL_HERE";

export const seedRetailers = [
  {
    slug: "store-a",
    name: "Store A",
    websiteUrl: "https://example.com/store-a",
    country: "EU",
    currency: "EUR",
    shippingInfo: "Demo: free shipping over €60 (placeholder)",
    affiliateNetwork: "Demo network (placeholder)",
    allowedDomains: ["example.com"],
    priceFactor: 0.95,
  },
  {
    slug: "store-b",
    name: "Store B",
    websiteUrl: "https://example.com/store-b",
    country: "EU",
    currency: "EUR",
    shippingInfo: "Demo: 2–4 working days (placeholder)",
    affiliateNetwork: "Demo network (placeholder)",
    allowedDomains: ["example.com"],
    priceFactor: 0.99,
  },
  {
    slug: "store-c",
    name: "Store C",
    websiteUrl: "https://example.com/store-c",
    country: "EU",
    currency: "EUR",
    shippingInfo: "Demo: free returns within 30 days (placeholder)",
    affiliateNetwork: "Demo network (placeholder)",
    allowedDomains: ["example.com"],
    priceFactor: 1.04,
  },
] as const;
