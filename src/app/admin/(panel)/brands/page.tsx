import type { Metadata } from "next";
import { adminListBrands } from "@/server/repositories/admin";
import { BrandForm } from "@/components/admin/EntityForms";

export const metadata: Metadata = { title: "Brands" };

export default async function AdminBrands() {
  const brands = await adminListBrands();
  return (
    <main className="max-w-5xl">
      <h1 className="display text-5xl">Brands</h1>
      <p className="mt-3 text-ink-2">Each brand gets its own page with its rackets. A brand can only be deleted once it has no rackets.</p>

      <details className="plate mt-6 p-5" open={brands.length === 0}>
        <summary className="title cursor-pointer text-xl">Add a brand</summary>
        <div className="mt-4">
          <BrandForm />
        </div>
      </details>

      <ul className="mt-4 space-y-3">
        {brands.map((b) => (
          <li key={b.id}>
            <details className="plate p-5">
              <summary className="flex cursor-pointer flex-wrap items-baseline justify-between gap-3">
                <span className="title text-xl">{b.name}</span>
                <span className="text-sm text-ink-2">
                  /brands/{b.slug} · <span className="num">{b.rackets}</span> racket{b.rackets === 1 ? "" : "s"}
                </span>
              </summary>
              <div className="mt-4">
                <BrandForm brand={b} />
              </div>
            </details>
          </li>
        ))}
      </ul>
    </main>
  );
}
