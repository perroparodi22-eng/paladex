import type { Metadata } from "next";
import { adminListRetailers } from "@/server/repositories/admin";
import { RetailerForm } from "@/components/admin/EntityForms";

export const metadata: Metadata = { title: "Retailers" };

export default async function AdminRetailers() {
  const retailers = await adminListRetailers();
  return (
    <main className="max-w-5xl">
      <h1 className="display text-5xl">Retailers</h1>
      <p className="mt-3 max-w-3xl text-ink-2">
        Shops that sell rackets. Offers for each racket are edited on the racket itself. The allowed domains are the safety net of the affiliate
        redirect: a link pointing anywhere else is never followed.
      </p>

      <details className="plate mt-6 p-5" open={retailers.length === 0}>
        <summary className="title cursor-pointer text-xl">Add a retailer</summary>
        <div className="mt-4">
          <RetailerForm />
        </div>
      </details>

      <ul className="mt-4 space-y-3">
        {retailers.map((r) => (
          <li key={r.id}>
            <details className="plate p-5">
              <summary className="flex cursor-pointer flex-wrap items-baseline justify-between gap-3">
                <span className="title text-xl">
                  {r.name} {r.isDemo && <span className="badge badge-warn ml-1 align-middle">Demo</span>} {!r.active && <span className="badge ml-1 align-middle">Inactive</span>}
                </span>
                <span className="text-sm text-ink-2">
                  <span className="num">{r.offers}</span> offer{r.offers === 1 ? "" : "s"} · {r.allowedDomains.join(", ") || "no allowed domains yet"}
                </span>
              </summary>
              <div className="mt-4">
                <RetailerForm retailer={r} />
              </div>
            </details>
          </li>
        ))}
      </ul>
    </main>
  );
}
