import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-[200] focus:rounded-xl focus:bg-court focus:px-4 focus:py-2 focus:text-on-court"
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id="content" className="min-h-[60vh]">
        {children}
      </main>
      <SiteFooter />
    </>
  );
}
