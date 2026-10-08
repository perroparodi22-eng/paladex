import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { eq } from "drizzle-orm";
import { getDb, schema } from "@/server/db";
import { getRacketForPreview } from "@/server/repositories/rackets";
import { RacketDetail } from "@/components/racket/RacketDetail";
import { ViewerBridgeProvider } from "@/components/three/ViewerBridge";
import { Icon } from "@/components/ui/Icon";

export const metadata: Metadata = { title: "Preview" };

/** The racket page exactly as it will publish, drafts included. Never cached, never public. */
export default async function AdminRacketPreview({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isInteger(numericId) || numericId <= 0) notFound();
  const db = await getDb();
  const [row] = await db.select({ slug: schema.products.slug, status: schema.products.status }).from(schema.products).where(eq(schema.products.id, numericId)).limit(1);
  if (!row) notFound();
  const racket = await getRacketForPreview(row.slug);
  if (!racket) notFound();
  return (
    <main className="-mx-4 sm:-mx-6 lg:-mx-10">
      <div className="sticky top-0 z-40 mx-4 mb-6 flex flex-wrap items-center justify-between gap-3 rounded-full border border-white/10 bg-surface-2 px-5 py-2.5 text-sm text-white shadow-lift sm:mx-6 lg:mx-10">
        <p>
          <strong className="font-semibold">{row.status === "published" ? "Preview of the live page" : "Draft preview, not public"}</strong>
          <span className="text-white/70"> · /rackets/{row.slug}</span>
        </p>
        <div className="flex gap-2">
          <Link href={`/admin/rackets/${numericId}`} className="btn btn-primary btn-sm">
            <Icon name="edit" size={16} /> Back to editing
          </Link>
        </div>
      </div>
      <ViewerBridgeProvider>
        <RacketDetail racket={racket} others={[]} />
      </ViewerBridgeProvider>
    </main>
  );
}
