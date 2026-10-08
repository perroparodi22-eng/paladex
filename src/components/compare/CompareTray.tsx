"use client";
/** Docked tray listing the rackets picked for comparison. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCompare } from "./CompareProvider";
import { Icon } from "@/components/ui/Icon";
import { MAX_COMPARE } from "@/lib/compare";

export function CompareTray() {
  const { items, remove, clear } = useCompare();
  const pathname = usePathname();
  if (!items.length || pathname.startsWith("/compare") || pathname.startsWith("/admin")) return null;
  const href = `/compare?rackets=${items.map((i) => i.slug).join(",")}`;
  return (
    <aside aria-label="Comparison" className="fixed inset-x-0 bottom-0 z-40 px-3 pb-[max(12px,env(safe-area-inset-bottom))]">
      <div className="plate mx-auto flex max-w-4xl items-center gap-3 bg-surface/95 p-2 pl-4 shadow-2xl">
        <span className="label hidden whitespace-nowrap sm:inline">
          Compare <span className="num text-ink">{items.length}</span>/{MAX_COMPARE}
        </span>
        <ul className="no-scrollbar flex min-w-0 flex-1 gap-2 overflow-x-auto">
          {items.map((i) => (
            <li key={i.slug} className="flex shrink-0 items-center gap-1 rounded-xl border border-ink/12 bg-surface-2 py-1 pl-2.5 pr-1 text-sm">
              <span className="max-w-[10rem] truncate">
                <span className="text-ink-2">{i.brand}</span> {i.name}
              </span>
              <button type="button" onClick={() => remove(i.slug)} className="grid h-8 w-8 place-items-center text-ink-2 hover:text-ink" aria-label={`Remove ${i.brand} ${i.name} from comparison`}>
                <Icon name="close" size={14} />
              </button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={clear} className="btn btn-ghost btn-sm hidden sm:inline-flex">
          Clear
        </button>
        <Link href={href} className="btn btn-primary btn-sm" aria-disabled={items.length < 2} onClick={(e) => items.length < 2 && e.preventDefault()}>
          {items.length < 2 ? "Add one more" : "Compare in 3D"}
          <Icon name="arrowRight" size={16} />
        </Link>
      </div>
    </aside>
  );
}
