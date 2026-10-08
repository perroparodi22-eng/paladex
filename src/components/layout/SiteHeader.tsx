"use client";
/**
 * Header: a plain three-line menu button, then the logo, the name and
 * "Rackets 3D Showroom" on the left; search on the right. The menu slides in
 * from the left and puts its close button exactly where the menu button was,
 * so opening and closing happen in the same spot.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { siteConfig } from "@/config/site";
import { LogoMark } from "./Logo";
import { Icon } from "@/components/ui/Icon";
import { Dialog } from "@/components/ui/Dialog";
import { SearchDialog } from "@/components/search/SearchDialog";
import { cn } from "@/lib/cn";

function MenuBars() {
  return (
    <span aria-hidden className="flex w-[22px] flex-col gap-[5px]">
      <span className="h-[2px] w-full rounded-full bg-current" />
      <span className="h-[2px] w-full rounded-full bg-current" />
      <span className="h-[2px] w-full rounded-full bg-current" />
    </span>
  );
}

const menuButton = "grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink transition-colors hover:bg-white/8";

export function SiteHeader() {
  const pathname = usePathname();
  const [menu, setMenu] = useState(false);
  const [search, setSearch] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || (e.target as HTMLElement)?.isContentEditable;
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // A sentinel at the top of the page tells us when the header has content under it.
  useEffect(() => {
    const sentinel = document.getElementById("top-sentinel");
    if (!sentinel) return;
    const io = new IntersectionObserver(([e]) => setScrolled(!e.isIntersecting));
    io.observe(sentinel);
    return () => io.disconnect();
  }, []);

  useEffect(() => setMenu(false), [pathname]);

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      <span id="top-sentinel" aria-hidden className="absolute left-0 top-0 h-2 w-px" />
      <header
        className={cn(
          "sticky top-0 z-50 transition-[background-color,border-color] duration-500",
          // Solid, no backdrop blur: blurring the 3D canvas underneath on every scroll frame is what made scrolling heavy.
          scrolled ? "border-b border-white/6 bg-ground" : "border-b border-transparent",
        )}
      >
        <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-2 px-4 sm:px-6 lg:px-10">
          <button
            type="button"
            onClick={() => setMenu(true)}
            aria-expanded={menu}
            aria-controls="site-menu"
            aria-label="Open menu"
            title="Menu"
            className={cn(menuButton, "-ml-2.5")}
          >
            <MenuBars />
          </button>
          <Link href="/" className="group flex items-center gap-2.5" aria-label={`${siteConfig.name}, home`}>
            <LogoMark className="h-8 w-8 transition-transform duration-500 group-hover:-rotate-12" />
            <span className="display text-[1.3rem] leading-none">{siteConfig.name}</span>
            <span aria-hidden className="mx-1 hidden h-4 w-px bg-white/15 sm:block" />
            <span className="hidden text-sm text-ink-2 sm:inline">{siteConfig.tagline2}</span>
          </Link>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setSearch(true)}
              className="grid h-11 w-11 place-items-center rounded-full text-ink-2 transition-colors hover:bg-white/6 hover:text-ink"
              aria-label="Search rackets and brands"
            >
              <Icon name="search" size={20} />
            </button>
          </div>
        </div>
      </header>

      <Dialog open={menu} onClose={() => setMenu(false)} title="Menu" variant="drawer" bare>
        <div id="site-menu" className="flex h-16 items-center gap-2 px-4 sm:px-6 lg:px-10">
          <button type="button" onClick={() => setMenu(false)} aria-label="Close menu" title="Close menu" className={cn(menuButton, "-ml-2.5")}>
            <Icon name="close" size={22} />
          </button>
          <LogoMark className="h-8 w-8" />
          <h2 className="display text-[1.3rem] leading-none">Menu</h2>
        </div>
        <nav aria-label="Main" className="flex h-[calc(100%-4rem)] flex-col px-4 pb-6 pt-2 sm:px-6">
          <ul className="space-y-1">
            {[{ href: "/", label: "Home", note: "Back to the start" }, ...siteConfig.nav].map((item, i) => (
              <li key={item.href} className="rise" style={{ ["--beat" as string]: i + 1 }}>
                <Link
                  href={item.href}
                  aria-current={isActive(item.href) ? "page" : undefined}
                  className={cn(
                    "group flex items-center justify-between gap-4 rounded-2xl px-4 py-4 transition-colors hover:bg-white/5",
                    isActive(item.href) && "bg-white/6",
                  )}
                >
                  <span>
                    <span className="display block text-[1.9rem]">{item.label}</span>
                    <span className="mt-1 block text-sm text-ink-2">{item.note}</span>
                  </span>
                  <Icon name="arrowRight" className="shrink-0 text-ink-3 transition-transform duration-300 group-hover:translate-x-1 group-hover:text-ink" />
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-auto space-y-3 pt-8">
            <button
              type="button"
              className="btn btn-secondary w-full"
              onClick={() => {
                setMenu(false);
                setSearch(true);
              }}
            >
              <Icon name="search" size={18} /> Search rackets and brands
            </button>
            <p className="px-1 text-xs leading-relaxed text-ink-3">
              {siteConfig.name} may earn a commission on purchases through retailer links.{" "}
              <Link href="/legal/affiliate-disclosure" className="underline hover:text-ink">
                How this works
              </Link>
            </p>
          </div>
        </nav>
      </Dialog>
      <SearchDialog open={search} onClose={() => setSearch(false)} />
    </>
  );
}
