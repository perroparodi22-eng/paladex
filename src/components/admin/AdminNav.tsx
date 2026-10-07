"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogoMark } from "@/components/layout/Logo";
import { Icon, type IconName } from "@/components/ui/Icon";
import { logout } from "@/app/admin/actions";
import { siteConfig } from "@/config/site";
import { cn } from "@/lib/cn";

const LINKS: Array<{ href: string; label: string; icon: IconName; exact?: boolean }> = [
  { href: "/admin", label: "Overview", icon: "grid", exact: true },
  { href: "/admin/rackets", label: "Rackets", icon: "racket" },
  { href: "/admin/brands", label: "Brands", icon: "layers" },
  { href: "/admin/retailers", label: "Retailers & offers", icon: "bag" },
  { href: "/admin/insights", label: "Clicks & events", icon: "target" },
];

export function AdminNav() {
  const path = usePathname();
  const isActive = (l: (typeof LINKS)[number]) => (l.exact ? path === l.href : path === l.href || path.startsWith(`${l.href}/`));
  return (
    <aside className="sticky top-0 z-30 border-b border-ink/8 bg-surface lg:h-dvh lg:border-b-0 lg:border-r">
      <div className="flex items-center gap-3 px-4 py-3 lg:px-5 lg:py-5">
        <Link href="/admin" className="flex items-center gap-2.5">
          <LogoMark className="h-7 w-7" />
          <span className="title text-[1.35rem] font-bold leading-none">
            {siteConfig.name} <span className="text-ink-2">admin</span>
          </span>
        </Link>
      </div>
      <nav aria-label="Admin" className="no-scrollbar flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible lg:px-3 lg:pb-0">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            aria-current={isActive(l) ? "page" : undefined}
            className={cn(
              "flex min-h-10 shrink-0 items-center gap-2.5 rounded-xl px-3 font-label text-sm font-semibold text-ink-2 transition-colors hover:bg-ink/5 hover:text-ink",
              isActive(l) && "bg-court/15 text-ink",
            )}
          >
            <Icon name={l.icon} size={18} />
            {l.label}
          </Link>
        ))}
      </nav>
      <div className="hidden lg:absolute lg:inset-x-0 lg:bottom-0 lg:block lg:border-t lg:border-ink/8 lg:p-3">
        <Link href="/" className="flex min-h-10 items-center gap-2.5 rounded-xl px-3 font-label text-sm font-semibold text-ink-2 hover:bg-ink/5 hover:text-ink">
          <Icon name="external" size={18} /> View site
        </Link>
        <form action={logout}>
          <button type="submit" className="flex min-h-10 w-full items-center gap-2.5 rounded-xl px-3 font-label text-sm font-semibold text-ink-2 hover:bg-ink/5 hover:text-ink">
            <Icon name="logout" size={18} /> Sign out
          </button>
        </form>
      </div>
      <form action={logout} className="absolute right-3 top-2.5 lg:hidden">
        <button type="submit" className="btn btn-ghost btn-sm" aria-label="Sign out">
          <Icon name="logout" size={18} />
        </button>
      </form>
    </aside>
  );
}
