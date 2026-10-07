import type { Metadata, Viewport } from "next";
import { preload } from "react-dom";
import { siteConfig, siteUrl, indexingAllowed } from "@/config/site";
import "./globals.css";

/* One variable family (Google Sans Flex, self-hosted in public/fonts) carries every role
   through its width, roundness and optical-size axes. See the @font-face rules in globals.css. */
const FONT_LATIN = "/fonts/google-sans-flex-v23-latin.woff2";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl("/")),
  title: {
    default: `${siteConfig.name}: ${siteConfig.tagline}`,
    template: `%s · ${siteConfig.name}`,
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  robots: indexingAllowed() ? { index: true, follow: true } : { index: false, follow: false },
  openGraph: { siteName: siteConfig.name, type: "website", locale: "en_GB" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  preload(FONT_LATIN, { as: "font", type: "font/woff2", crossOrigin: "anonymous" });
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
