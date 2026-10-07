import type { Metadata } from "next";
import { siteConfig } from "@/config/site";

export const metadata: Metadata = {
  title: { default: `Admin · ${siteConfig.name}`, template: `%s · Admin · ${siteConfig.name}` },
  robots: { index: false, follow: false },
};

export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-dvh bg-ground text-ink">{children}</div>;
}
