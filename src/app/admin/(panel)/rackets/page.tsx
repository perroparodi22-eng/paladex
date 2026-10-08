import type { Metadata } from "next";
import Link from "next/link";
import { adminListRackets } from "@/server/repositories/admin";
import { ProvenanceBadge } from "@/components/racket/ProvenanceBadge";
import { Icon } from "@/components/ui/Icon";
import { SHAPE_INFO } from "@/domain/vocab";

export const metadata: Metadata = { title: "Rackets" };

export default async function AdminRackets({ searchParams }: { searchParams: Promise<{ q?: string; deleted?: string }> }) {
  const { q = "", deleted } = await searchParams;
  const rows = await adminListRackets(q.slice(0, 80));
  return (
    <main>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="display text-5xl">Rackets</h1>
        <Link href="/admin/rackets/new" className="btn btn-primary">
          <Icon name="plus" size={18} /> New racket
        </Link>
      </div>
      {deleted !== undefined && (
        <p role="status" className="mt-5 rounded-2xl bg-court-tint px-4 py-3 text-sm text-court-deep">
          Deleted {deleted ? <strong>{deleted}</strong> : "the racket"}. Its pages are gone from the site.
        </p>
      )}
      <form className="mt-6 flex max-w-lg gap-2" role="search">
        <label className="relative flex-1">
          <span className="sr-only">Search rackets</span>
          <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-2" />
          <input name="q" defaultValue={q} placeholder="Search by name or slug…" className="field rounded-full pl-11" />
        </label>
        <button type="submit" className="btn btn-secondary">
          Search
        </button>
      </form>

      <div className="mt-6 overflow-x-auto rounded-[24px] border border-ink/6 bg-surface shadow-soft">
        <table className="w-full min-w-[820px] text-sm">
          <caption className="sr-only">All rackets, most recently updated first</caption>
          <thead>
            <tr className="border-b border-ink/8 text-left text-[0.8125rem] text-ink-2">
              <th scope="col" className="px-4 py-3 font-semibold">Racket</th>
              <th scope="col" className="px-4 py-3 font-semibold">Status</th>
              <th scope="col" className="px-4 py-3 font-semibold">3D model</th>
              <th scope="col" className="px-4 py-3 font-semibold">Offers</th>
              <th scope="col" className="px-4 py-3 font-semibold">Updated</th>
              <th scope="col" className="px-4 py-3 font-semibold">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-ink/6 last:border-0">
                <td className="px-4 py-3">
                  <Link href={`/admin/rackets/${r.id}`} className="font-semibold text-ink hover:underline">
                    {r.brand} {r.name}
                  </Link>
                  <p className="text-xs text-ink-3">
                    /{r.slug}
                    {r.shape ? ` · ${SHAPE_INFO[r.shape].label}` : ""}
                    {r.featured ? " · featured" : ""}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <span className={r.status === "published" ? "badge bg-ok/15 text-ok" : "badge"}>{r.status === "published" ? "Published" : "Draft"}</span>
                </td>
                <td className="px-4 py-3">
                  <ProvenanceBadge status={r.modelStatus} />
                </td>
                <td className="px-4 py-3">
                  <span className="num">{r.offers}</span>
                  {r.placeholderLinks > 0 && <span className="badge badge-warn ml-2">{r.placeholderLinks} without link</span>}
                </td>
                <td className="num px-4 py-3 text-ink-2">{new Date(r.updatedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    <Link href={`/admin/rackets/${r.id}`} className="btn btn-ghost btn-sm">
                      <Icon name="edit" size={16} /> Edit
                    </Link>
                    <Link href={`/admin/rackets/${r.id}/preview`} className="btn btn-ghost btn-sm">
                      <Icon name="eye" size={16} /> Preview
                    </Link>
                    {r.status === "published" && (
                      <Link href={`/rackets/${r.slug}`} className="btn btn-ghost btn-sm" target="_blank">
                        <Icon name="external" size={16} /> Live
                      </Link>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-2">
                  {q ? `No rackets match “${q}”.` : "No rackets yet."}{" "}
                  <Link href="/admin/rackets/new" className="text-court underline">
                    Add one
                  </Link>
                  .
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}
