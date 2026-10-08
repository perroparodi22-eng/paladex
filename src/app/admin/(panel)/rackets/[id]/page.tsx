import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { adminGetRacket, adminOptions, blankRacket } from "@/server/repositories/admin";
import { RacketForm } from "@/components/admin/RacketForm";
import { Icon } from "@/components/ui/Icon";

export const metadata: Metadata = { title: "Edit racket" };

export default async function AdminRacketEdit({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ created?: string }> }) {
  const [{ id }, { created }] = await Promise.all([params, searchParams]);
  const options = await adminOptions();
  if (!options.brands.length) {
    return (
      <main className="plate max-w-xl p-6">
        <h1 className="title text-2xl">Add a brand first</h1>
        <p className="mt-2 text-ink-2">Every racket belongs to a brand.</p>
        <Link href="/admin/brands" className="btn btn-primary mt-4">
          Go to brands
        </Link>
      </main>
    );
  }
  const isNew = id === "new";
  const numericId = Number(id);
  if (!isNew && (!Number.isInteger(numericId) || numericId <= 0)) notFound();
  const racket = isNew ? blankRacket(options.brands[0].id) : await adminGetRacket(numericId);
  if (!racket) notFound();

  return (
    <main>
      <Link href="/admin/rackets" className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
        <Icon name="arrowLeft" size={16} /> All rackets
      </Link>
      <h1 className="display mt-2 text-5xl">{isNew ? "New racket" : racket.basics.name}</h1>
      {created && (
        <p role="status" className="mt-4 rounded-2xl bg-court-tint px-4 py-3 text-sm text-court-deep">
          Created. {racket.basics.status === "published" ? "It is live on the site." : "It is a draft: only you can see it, through Preview."}
        </p>
      )}
      <RacketForm initial={racket} brands={options.brands} retailers={options.retailers} />
    </main>
  );
}
