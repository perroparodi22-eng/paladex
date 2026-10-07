import Link from "next/link";
import { siteConfig } from "@/config/site";
import { cn } from "@/lib/cn";

/** Mark: a racket face tilted into the shot, with the ball just hit off it. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <g transform="rotate(-18 15 17)">
        <rect x="13.1" y="21.5" width="3.8" height="9" rx="1.9" fill="#8b919c" />
        <ellipse cx="15" cy="12.6" rx="9.2" ry="10.4" fill="#eceef1" />
        <circle cx="11.6" cy="9.6" r="1.25" fill="#0a0b0d" />
        <circle cx="18.4" cy="9.6" r="1.25" fill="#0a0b0d" />
        <circle cx="15" cy="14.4" r="1.25" fill="#0a0b0d" />
      </g>
      <circle cx="25.4" cy="6.6" r="4.3" fill="#d9f04a" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link href="/" className={cn("group flex items-center gap-2", className)} aria-label={`${siteConfig.name}, home`}>
      <LogoMark className="h-8 w-8 transition-transform duration-500 group-hover:-rotate-12" />
      <span className="display text-[1.3rem] leading-none text-ink">{siteConfig.name}</span>
    </Link>
  );
}
