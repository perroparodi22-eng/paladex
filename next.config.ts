import type { NextConfig } from "next";

/**
 * Hosts allowed to serve 3D models and images (besides this origin).
 * Comma-separated origins, e.g. "https://assets.paladex.example,https://pub-xyz.r2.dev".
 * Used by the Content-Security-Policy (connect-src for model downloads) and next/image.
 */
const assetOrigins = (process.env.ASSET_ORIGINS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

/** Optional analytics script origin (e.g. https://plausible.io). Empty = none. */
const analyticsOrigin = process.env.NEXT_PUBLIC_ANALYTICS_SCRIPT_ORIGIN?.trim() ?? "";

const isProd = process.env.NODE_ENV === "production";

/**
 * Static Content-Security-Policy. Pages are statically generated, so per-request
 * nonces are not available; inline scripts Next.js emits for hydration need
 * 'unsafe-inline'. Everything else is locked down. 'wasm-unsafe-eval' is required
 * by the Meshopt/Draco/Basis decoders used for compressed 3D models.
 * See docs/SECURITY.md for the trade-offs and how to move to nonces.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${analyticsOrigin ? ` ${analyticsOrigin}` : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self'",
  `connect-src 'self' blob: data:${assetOrigins.length ? ` ${assetOrigins.join(" ")}` : ""}${analyticsOrigin ? ` ${analyticsOrigin}` : ""}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  ...(isProd
    ? [
        { key: "Content-Security-Policy", value: csp },
        // Add "; preload" only when deliberately submitting the domain to hstspreload.org.
        { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
      ]
    : []),
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=(), fullscreen=(self), xr-spatial-tracking=(self)",
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Serverless hosts (Netlify preview): ship the SQLite file built during the build with the
  // server code. It is copied to a writable folder on first use (see DATABASE_TEMPLATE).
  outputFileTracingIncludes: { "/**": ["./data/paladex.db"] },
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: assetOrigins.map((origin) => {
      const url = new URL(origin);
      return { protocol: url.protocol.replace(":", "") as "https" | "http", hostname: url.hostname, pathname: "/**" };
    }),
  },
  // Comparison is parked for now and brands live inside the rackets browser.
  async redirects() {
    return [
      { source: "/compare", destination: "/rackets", permanent: false },
      { source: "/compare/:pair", destination: "/rackets", permanent: false },
      { source: "/brands", destination: "/rackets", permanent: false },
    ];
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Models are versioned through their file name or ?v= query; a day of caching keeps replacements visible.
      {
        source: "/models/:path*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=86400, stale-while-revalidate=604800" },
          { key: "Access-Control-Allow-Origin", value: "*" },
        ],
      },
      {
        source: "/decoders/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=2592000, immutable" }],
      },
      // Font files carry their version in the name (…-v23-…); give a new name when replacing one.
      {
        source: "/fonts/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      // Never let admin or affiliate redirect responses be cached or indexed.
      { source: "/admin/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }, { key: "Cache-Control", value: "no-store" }] },
      { source: "/go/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
    ];
  },
};

export default nextConfig;
