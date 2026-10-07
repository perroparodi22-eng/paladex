import Link from "next/link";
import { siteConfig } from "@/config/site";
import { LogoMark } from "./Logo";

/** The close of every page: the sign-off, the map of the site, the disclosure. */
export function SiteFooter() {
  return (
    <footer className="relative mt-32 border-t border-white/6">
      <div className="mx-auto max-w-[1440px] px-4 pb-10 pt-16 sm:px-6 lg:px-10">
        <div className="grid gap-12 lg:grid-cols-[1.1fr_2fr]">
          <div className="max-w-md">
            <div className="flex items-center gap-2.5">
              <LogoMark className="h-9 w-9" />
              <span className="display text-[1.6rem] leading-none">{siteConfig.name}</span>
            </div>
            <p className="display mt-8 text-[clamp(1.8rem,3.4vw,2.6rem)]">See it from every side before you buy it.</p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {siteConfig.footer.map((col) => (
              <div key={col.title}>
                <p className="mb-3 text-sm font-semibold text-ink">{col.title}</p>
                <ul className="space-y-2.5">
                  {col.links.map((l) => (
                    <li key={l.href}>
                      <Link href={l.href} className="text-sm text-ink-2 transition-colors hover:text-ink">
                        {l.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <p className="mt-14 max-w-3xl text-sm leading-relaxed text-ink-3">
          <strong className="font-semibold text-ink-2">Affiliate disclosure.</strong> {siteConfig.name} may earn a commission when you buy through certain
          links. It doesn&apos;t change the price you pay, and it doesn&apos;t influence our evaluations.{" "}
          <Link href="/legal/affiliate-disclosure" className="text-ink-2 underline underline-offset-4 hover:text-ink">
            Read the affiliate disclosure
          </Link>
          .
        </p>
        <div className="mt-6 flex flex-col gap-2 border-t border-white/6 pt-6 text-xs text-ink-3 sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {new Date().getFullYear()} {siteConfig.name}. Platform scores are our own evaluations, not manufacturer measurements.
          </p>
          <p>Prices and retailer links in this preview are sample data.</p>
        </div>
      </div>
    </footer>
  );
}
