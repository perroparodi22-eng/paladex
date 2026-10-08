import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export function Container({ children, className, wide = false }: { children: ReactNode; className?: string; wide?: boolean }) {
  return <div className={cn("mx-auto w-full px-4 sm:px-6 lg:px-10", wide ? "max-w-[1600px]" : "max-w-[1440px]", className)}>{children}</div>;
}

/** Section heading: the wide, slanted on-air voice, with an optional action pill. */
export function SectionHeading({
  title,
  intro,
  action,
  as: Tag = "h2",
  className,
  id,
}: {
  title: ReactNode;
  intro?: ReactNode;
  action?: { href: string; label: string };
  as?: "h1" | "h2";
  className?: string;
  id?: string;
}) {
  return (
    <div className={cn("mb-8 sm:mb-10", className)}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Tag id={id} className={cn("display max-w-4xl", Tag === "h1" ? "text-[clamp(2.6rem,6.4vw,5.25rem)]" : "text-[clamp(2.1rem,4.2vw,3.5rem)]")}>
          {title}
        </Tag>
        {action && (
          <Link href={action.href} className="btn btn-secondary btn-sm shrink-0">
            {action.label} <Icon name="arrowRight" size={16} />
          </Link>
        )}
      </div>
      {intro && <div className="mt-4 max-w-2xl text-[1.0625rem] leading-relaxed text-ink-2">{intro}</div>}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: Array<{ name: string; href?: string }> }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-5">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-ink-3">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-1.5">
            {i > 0 && <Icon name="chevronRight" size={14} className="text-ink-3/60" />}
            {it.href ? (
              <Link href={it.href} className="hover:text-ink">
                {it.name}
              </Link>
            ) : (
              <span aria-current="page" className="text-ink-2">
                {it.name}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
